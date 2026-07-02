"""Step 1 — register (allocate) a new INTERNAL party on the C8 DevNet validator.

Uses the validator Admin API: POST /v0/admin/users onboards a ledger user and
allocates a fresh internal party (party hint = C8_PARTY_HINT), including the
wallet install needed later for Canton Coin. Idempotent: if the user already
exists, the party id is resolved via the Ledger API (GET /v2/users/{id}).

Cross-checks the allocation at the Ledger API level via GET /v2/parties/{party}.
Writes the result to PARTY_ID.txt.
"""

import urllib.parse

import common as c


def resolve_existing_party(token: str, name: str):
    enc = urllib.parse.quote(name, safe="")
    status, data = c.ledger("GET", f"/v2/users/{enc}", token, quiet=True)
    if status == 200:
        return data.get("user", {}).get("primaryParty")
    return None


def main() -> None:
    token = c.get_token()
    name = c.PARTY_HINT

    print(f"Listing users already onboarded on the validator (admin API) ...")
    status, users = c.validator("GET", "/v0/admin/users", token)
    if status != 200:
        c.die(f"GET /v0/admin/users failed (HTTP {status}) — token lacks validator admin rights?")
    usernames = users.get("usernames", [])
    print(f"  {len(usernames)} users onboarded")

    if name in usernames:
        print(f"User '{name}' already onboarded — resolving its party via Ledger API")
        party = resolve_existing_party(token, name)
        if not party:
            c.die(f"user '{name}' exists but primary party could not be resolved")
        onboard_response = {"note": "user already existed, party resolved via GET /v2/users"}
    else:
        print(f"Onboarding new user+party via POST /v0/admin/users (name='{name}') ...")
        status, data = c.validator("POST", "/v0/admin/users", token, {"name": name})
        if status != 200:
            c.die(f"onboarding failed: HTTP {status}")
        party = data["party_id"]
        onboard_response = data

    print(f"PARTY ID: {party}")

    # Ledger-API-level proof that the party exists on the participant.
    enc_party = urllib.parse.quote(party, safe="")
    pd_status, party_details = c.ledger("GET", f"/v2/parties/{enc_party}", token)

    c.PARTY_ID_FILE.write_text(party + "\n")
    print(f"  wrote {c.PARTY_ID_FILE.name}")

    c.save_evidence(
        "02-create-party",
        {
            "admin_api_endpoint": f"{c.VALIDATOR_API}/v0/admin/users",
            "requested_name": name,
            "onboard_response": onboard_response,
            "party_id": party,
            "ledger_api_party_details": {"status": pd_status, "body": party_details},
        },
    )
    print("PARTY ALLOCATION OK — post this PartyId in the hackathon group for the CC drop.")


if __name__ == "__main__":
    main()
