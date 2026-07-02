"""Step 2 — set up a TransferPreapproval with the DevNet validator.

Low-level flow, entirely via the JSON Ledger API command service:
  1. Look up the validator operator party (provider) and the DSO party.
  2. Grant our ledger user actAs/readAs rights on our new party (Ledger API
     user management — possible because the token user is ParticipantAdmin).
  3. Create the DAML contract
       #splice-wallet:Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal
     with our party as `receiver` (signatory) and the validator as `provider`,
     via POST /v2/commands/submit-and-wait-for-transaction.
  4. Poll until the validator's automation exercises
     TransferPreapprovalProposal_Accept, producing the actual
     Splice.AmuletRules:TransferPreapproval contract (validator pays the fee).

Idempotent: skips creation if a proposal or accepted preapproval already exists.
"""

import json
import time
import urllib.parse
import uuid

import common as c

PREAPPROVAL_TEMPLATE = "#splice-amulet:Splice.AmuletRules:TransferPreapproval"
POLL_ATTEMPTS = 10
POLL_SECONDS = 6


def acs_by_template(token: str, party: str, template_id: str) -> list:
    offset = c.ledger_end_offset(token)
    status, data = c.ledger(
        "POST",
        "/v2/state/active-contracts",
        token,
        {
            "activeAtOffset": offset,
            "eventFormat": {
                "filtersByParty": {
                    party: {
                        "cumulative": [
                            {
                                "identifierFilter": {
                                    "TemplateFilter": {
                                        "value": {
                                            "templateId": template_id,
                                            "includeCreatedEventBlob": False,
                                        }
                                    }
                                }
                            }
                        ]
                    }
                },
                "verbose": True,
            },
        },
        quiet=True,
    )
    if status != 200:
        c.die(f"ACS query failed: HTTP {status} {json.dumps(data)[:400]}")
    active = []
    for entry in data:
        contract = entry.get("contractEntry", {}).get("JsActiveContract")
        if contract:
            active.append(contract["createdEvent"])
    return active


def lookup_accepted_preapproval(token: str, party: str):
    enc = urllib.parse.quote(party, safe="")
    status, data = c.validator(
        "GET", f"/v0/scan-proxy/transfer-preapprovals/by-party/{enc}", token,
        ok=(200, 404), quiet=True,
    )
    return data if status == 200 else None


def create_proposal(token: str, party: str, provider: str, dso: str) -> dict:
    body = {
        "commands": {
            "commands": [
                {
                    "CreateCommand": {
                        "templateId": c.PREAPPROVAL_PROPOSAL_TEMPLATE,
                        "createArguments": {
                            "receiver": party,
                            "provider": provider,
                            "expectedDso": dso,
                        },
                    }
                }
            ],
            "commandId": f"c8lab-preapproval-{uuid.uuid4()}",
            "actAs": [party],
            "readAs": [party],
        }
    }
    print("Submitting CreateCommand for TransferPreapprovalProposal ...")
    print(f"  templateId: {c.PREAPPROVAL_PROPOSAL_TEMPLATE}")
    status, data = c.ledger("POST", "/v2/commands/submit-and-wait-for-transaction", token, body)
    if status != 200:
        c.die(f"create failed: HTTP {status}")
    return data


def main() -> None:
    token = c.get_token()
    party = c.read_party_id()
    print(f"Receiver party: {party}")

    status, vinfo = c.validator("GET", "/v0/validator-user", token, quiet=True)
    provider = vinfo["party_id"]
    status, dso_data = c.validator("GET", "/v0/scan-proxy/dso-party-id", token, quiet=True)
    dso = dso_data["dso_party_id"]
    print(f"Provider (validator operator): {provider}")
    print(f"DSO party:                     {dso}")

    c.ensure_act_read_rights(token, party)

    accepted = lookup_accepted_preapproval(token, party)
    if accepted:
        print("TransferPreapproval already accepted for this party — nothing to do.")
        c.save_evidence("03-preapproval-already-accepted", accepted)
        return

    proposals = acs_by_template(token, party, c.PREAPPROVAL_PROPOSAL_TEMPLATE)
    creation_tx = None
    if proposals:
        print(f"Found {len(proposals)} pending TransferPreapprovalProposal — skipping creation.")
    else:
        creation_tx = create_proposal(token, party, provider, dso)
        tx = creation_tx.get("transaction", {})
        update_id = tx.get("updateId")
        offset = tx.get("offset")
        cids = []
        for ev in tx.get("events", []):
            created = ev.get("CreatedEvent")
            if created:
                cids.append(created.get("contractId"))
        print(f"  updateId:   {update_id}")
        print(f"  offset:     {offset}")
        print(f"  contractId: {cids}")
        c.save_evidence("03-preapproval-proposal-created", creation_tx)

    print(f"Waiting for validator automation to accept (max {POLL_ATTEMPTS * POLL_SECONDS}s) ...")
    for attempt in range(1, POLL_ATTEMPTS + 1):
        time.sleep(POLL_SECONDS)
        # Ledger-level check: the accepted TransferPreapproval names us as stakeholder.
        active = acs_by_template(token, party, PREAPPROVAL_TEMPLATE)
        if active:
            print(f"ACCEPTED after ~{attempt * POLL_SECONDS}s — TransferPreapproval is active:")
            ev = active[0]
            print(f"  contractId: {ev.get('contractId')}")
            print(f"  templateId: {ev.get('templateId')}")
            evidence = {"acs_created_event": ev}
            scan_view = lookup_accepted_preapproval(token, party)
            if scan_view:
                evidence["scan_proxy_lookup"] = scan_view
            c.save_evidence("03-preapproval-accepted", evidence)
            print("PREAPPROVAL OK")
            return
        print(f"  attempt {attempt}/{POLL_ATTEMPTS}: not accepted yet")

    print("Proposal created but not yet accepted by validator automation.")
    print("Re-run this script later; it will only poll (creation is idempotent).")


if __name__ == "__main__":
    main()
