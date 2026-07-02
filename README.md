# Cantor8 Learner Bounty — "Touching the Ledger: A Canton Low-Level Lab"

Scripted, reproducible walkthrough of the C8 Canton DevNet lab: party
allocation, TransferPreapproval setup, ACS balance indexing over the token
standard `Holding` interface, and a hand-composed Canton Coin transfer — all
against the low-level Validator Admin API + JSON Ledger API (no wallet UI).

## Layout

```
scripts/
  common.py             shared auth / ledger / evidence helpers
  01_auth.py            OAuth2 client_credentials -> Bearer JWT + smoke tests
  02_create_party.py    allocate internal party (POST /v0/admin/users)
  03_preapproval.py     create TransferPreapprovalProposal via raw CreateCommand,
                        wait for validator automation to accept it
  04_balance.py         index the ACS, InterfaceFilter over Holding, sum amounts
  05_token_transfer.py  AmuletRules_DevNet_Tap (self-mint) + TransferPreapproval_Send
                        (hand-built PaymentTransferContext + disclosed contracts)
evidence/               raw API responses, timestamped (UTC)
PARTY_ID.txt            the allocated party id
NOTES.md                what worked / what failed and why
form-answers.md         draft answers for the bounty Google Form
```

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install httpx
cp .env.example .env    # fill in C8_CLIENT_SECRET (from the task doc)
.venv/bin/python scripts/01_auth.py
.venv/bin/python scripts/02_create_party.py
.venv/bin/python scripts/03_preapproval.py
.venv/bin/python scripts/04_balance.py
.venv/bin/python scripts/05_token_transfer.py
.venv/bin/python scripts/04_balance.py   # balance after the transfer
```

Every script is idempotent (safe to re-run) and fetches a fresh token
(tokens expire after 900s). `04_balance.py` accepts an optional party id
argument to inspect any other hosted party.

## Endpoints used

| Purpose | Endpoint |
|---|---|
| IdP token | `POST {keycloak}/realms/master/protocol/openid-connect/token` |
| Party allocation | `POST /api/validator/v0/admin/users` |
| Validator info | `GET /api/validator/v0/validator-user` |
| DSO party | `GET /api/validator/v0/scan-proxy/dso-party-id` |
| Reference data + blobs | `GET /api/validator/v0/scan-proxy/{amulet-rules,open-and-issuing-mining-rounds,transfer-preapprovals/by-party/*}` |
| User rights | `GET/POST /api/ledger/v2/users/{user}/rights` |
| Command submission | `POST /api/ledger/v2/commands/submit-and-wait-for-transaction` |
| ACS | `GET /api/ledger/v2/state/ledger-end` + `POST /api/ledger/v2/state/active-contracts` |

See `NOTES.md` for the full findings log (including why the wallet API and the
token standard registry endpoint are not usable with the hackathon token).
