"""Step 5 (stretch) — fund the party from the DevNet faucet choice, then
compose a Canton Coin transfer, entirely through the low-level JSON Ledger API.

No wallet endpoints are involved; every write is a hand-built DAML command:

  1. Fetch AmuletRules + the open OpenMiningRound from the validator's
     scan-proxy (contract ids AND created_event_blobs, used as
     `disclosedContracts` because our party is no stakeholder on them).
  2. Exercise `AmuletRules_DevNet_Tap` (controller = receiver = our party) to
     self-mint TAP_AMOUNT CC. DevNet-only choice; touches nobody else's funds.
  3. Look up the VALIDATOR party's TransferPreapproval via scan-proxy.
  4. Exercise `TransferPreapproval_Send` on it with sender = our party,
     transferring SEND_AMOUNT CC from our tapped Amulet to the validator
     operator. This is the preapproval settlement path that the Token Standard
     TransferFactory delegates to for pre-approved receivers.

Note: the full Token Standard round-trip (registry `transfer-factory` endpoint
+ `TransferFactory_Transfer`) needs the scan registry API, which is not
exposed on this node (scan-proxy /v0/scan-proxy/dso returns 502 and no public
scan host exists for the C8 network) — documented in NOTES.md.
"""

import urllib.parse
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import common as c

TAP_AMOUNT = "10.0"
SEND_AMOUNT = "1.0"
AMULET_RULES_TEMPLATE = "#splice-amulet:Splice.AmuletRules:AmuletRules"
PREAPPROVAL_TEMPLATE = "#splice-amulet:Splice.AmuletRules:TransferPreapproval"


def get_amulet_rules(token: str) -> dict:
    status, data = c.validator("GET", "/v0/scan-proxy/amulet-rules", token, quiet=True)
    if status != 200:
        c.die(f"scan-proxy amulet-rules failed: HTTP {status}")
    return data["amulet_rules"]


def get_ready_open_round(token: str) -> dict:
    status, data = c.validator(
        "GET", "/v0/scan-proxy/open-and-issuing-mining-rounds", token, quiet=True
    )
    if status != 200:
        c.die(f"scan-proxy mining-rounds failed: HTTP {status}")
    now = datetime.now(timezone.utc)
    ready = [
        r for r in data["open_mining_rounds"]
        if datetime.fromisoformat(r["contract"]["payload"]["opensAt"]) <= now
    ]
    if not ready:
        c.die("no open mining round is ready yet — retry in a minute")
    best = max(ready, key=lambda r: int(r["contract"]["payload"]["round"]["number"]))
    print(f"  using OpenMiningRound #{best['contract']['payload']['round']['number']}")
    return best


def tap(token: str, party: str, amulet_rules: dict, open_round: dict) -> dict:
    print(f"Exercising AmuletRules_DevNet_Tap for {TAP_AMOUNT} CC (receiver = our party) ...")
    return c.submit_and_wait_for_transaction(
        token,
        commands=[
            {
                "ExerciseCommand": {
                    "templateId": AMULET_RULES_TEMPLATE,
                    "contractId": amulet_rules["contract"]["contract_id"],
                    "choice": "AmuletRules_DevNet_Tap",
                    "choiceArgument": {
                        "receiver": party,
                        "amount": TAP_AMOUNT,
                        "openRound": open_round["contract"]["contract_id"],
                    },
                }
            }
        ],
        act_as=[party],
        command_id=f"c8lab-tap-{uuid.uuid4()}",
        disclosed=[c.as_disclosed(amulet_rules), c.as_disclosed(open_round)],
    )


def get_validator_preapproval(token: str, validator_party: str) -> dict:
    enc = urllib.parse.quote(validator_party, safe="")
    status, data = c.validator(
        "GET", f"/v0/scan-proxy/transfer-preapprovals/by-party/{enc}", token,
        ok=(200, 404), quiet=True,
    )
    if status != 200:
        c.die(f"validator party has no TransferPreapproval (HTTP {status}) — no send target")
    return data["transfer_preapproval"]


def send_via_preapproval(token: str, sender: str, preapproval: dict,
                         amulet_rules: dict, open_round: dict, input_cids: list) -> dict:
    print(f"Exercising TransferPreapproval_Send: {SEND_AMOUNT} CC "
          f"{sender.split('::')[0]} -> {preapproval['contract']['payload']['receiver'].split('::')[0]} ...")
    return c.submit_and_wait_for_transaction(
        token,
        commands=[
            {
                "ExerciseCommand": {
                    "templateId": PREAPPROVAL_TEMPLATE,
                    "contractId": preapproval["contract"]["contract_id"],
                    "choice": "TransferPreapproval_Send",
                    "choiceArgument": {
                        "context": {
                            "amuletRules": amulet_rules["contract"]["contract_id"],
                            "context": {
                                "openMiningRound": open_round["contract"]["contract_id"],
                                "issuingMiningRounds": [],
                                "validatorRights": [],
                                "featuredAppRight": None,
                            },
                        },
                        "inputs": [{"tag": "InputAmulet", "value": cid} for cid in input_cids],
                        "amount": SEND_AMOUNT,
                        "sender": sender,
                        "description": "Cantor8 learner lab: low-level preapproval transfer (stetang)",
                    },
                }
            }
        ],
        act_as=[sender],
        command_id=f"c8lab-send-{uuid.uuid4()}",
        disclosed=[
            c.as_disclosed(amulet_rules),
            c.as_disclosed(open_round),
            c.as_disclosed(preapproval),
        ],
    )


def tx_summary(tx_response: dict) -> dict:
    tx = tx_response.get("transaction", {})
    return {"updateId": tx.get("updateId"), "offset": tx.get("offset")}


def main() -> None:
    token = c.get_token()
    party = c.read_party_id()
    print(f"Party: {party}")
    c.ensure_act_read_rights(token, party)

    status, vinfo = c.validator("GET", "/v0/validator-user", token, quiet=True)
    validator_party = vinfo["party_id"]

    print("Fetching AmuletRules and open mining rounds from scan-proxy ...")
    amulet_rules = get_amulet_rules(token)
    open_round = get_ready_open_round(token)

    evidence = {"party": party, "validator_party": validator_party}

    # -- Tap (skip if we already hold enough unlocked CC) ---------------------
    unlocked = [h for h in c.acs_holdings(token, party)
                if not h["locked"] and h["instrument_id"] == "Amulet"]
    total = sum(Decimal(h["amount"]) for h in unlocked)
    if total >= Decimal(SEND_AMOUNT) * 2:
        print(f"Party already holds {total} CC unlocked — skipping tap.")
    else:
        tap_tx = tap(token, party, amulet_rules, open_round)
        evidence["tap"] = tap_tx
        print(f"  tap updateId: {tx_summary(tap_tx)['updateId']}")
        unlocked = [h for h in c.acs_holdings(token, party)
                    if not h["locked"] and h["instrument_id"] == "Amulet"]
        total = sum(Decimal(h["amount"]) for h in unlocked)
        print(f"  balance after tap: {total} CC across {len(unlocked)} Amulet(s)")

    # -- Preapproval-routed send back to the validator operator ---------------
    preapproval = get_validator_preapproval(token, validator_party)
    input_cids = [h["contract_id"] for h in unlocked]
    send_tx = send_via_preapproval(token, party, preapproval, amulet_rules,
                                   open_round, input_cids)
    evidence["send"] = send_tx
    summary = tx_summary(send_tx)
    print(f"  send updateId: {summary['updateId']}")
    print(f"  send offset:   {summary['offset']}")

    c.save_evidence("05-tap-and-preapproval-send", evidence)
    print("DONE — re-run 04_balance.py to see the change reflected in the ACS.")


if __name__ == "__main__":
    main()
