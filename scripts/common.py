"""Shared helpers for the Cantor8 Canton DevNet lab scripts.

Every script fetches a fresh OAuth token (they expire after 900s), talks to the
validator Admin API and/or the JSON Ledger API, and drops raw responses into
evidence/ with UTC-timestamped filenames.
"""

import base64
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
PARTY_ID_FILE = ROOT / "PARTY_ID.txt"

HOLDING_INTERFACE = "#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding"
PREAPPROVAL_PROPOSAL_TEMPLATE = (
    "#splice-wallet:Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal"
)

RETRYABLE_STATUS = {429, 502, 503, 504}


def load_env() -> dict:
    env = {}
    path = ROOT / ".env"
    if not path.exists():
        die(".env not found — copy .env.example to .env and fill in the secret")
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def die(msg: str) -> None:
    print(f"FATAL: {msg}")
    sys.exit(1)


ENV = load_env()
AUTH_URL = ENV["C8_AUTH_URL"]
CLIENT_ID = ENV["C8_CLIENT_ID"]
CLIENT_SECRET = ENV["C8_CLIENT_SECRET"]
VALIDATOR_API = ENV["C8_VALIDATOR_API"].rstrip("/")
LEDGER_API = ENV["C8_LEDGER_API"].rstrip("/")
PARTY_HINT = ENV.get("C8_PARTY_HINT", "c8lab-party")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save_evidence(name: str, payload) -> Path:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    path = EVIDENCE_DIR / f"{utc_stamp()}_{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    print(f"  evidence -> {path.relative_to(ROOT)}")
    return path


def jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def get_token() -> str:
    """client_credentials grant against Keycloak (realm master)."""
    resp = httpx.post(
        AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        die(f"token request failed: HTTP {resp.status_code} {resp.text[:300]}")
    return resp.json()["access_token"]


def api(
    method: str,
    url: str,
    token: str,
    json_body=None,
    ok=(200,),
    quiet: bool = False,
):
    """Single API call with one polite retry on 429/5xx. Returns (status, data)."""
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in (1, 2):
        resp = httpx.request(method, url, headers=headers, json=json_body, timeout=60)
        if resp.status_code in RETRYABLE_STATUS and attempt == 1:
            print(f"  {method} {url} -> HTTP {resp.status_code}, backing off 5s ...")
            time.sleep(5)
            continue
        break
    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": resp.text[:2000]}
    if not quiet:
        print(f"  {method} {url} -> HTTP {resp.status_code}")
    if resp.status_code not in ok:
        print(f"  response body: {json.dumps(data)[:800]}")
    return resp.status_code, data


def validator(method: str, path: str, token: str, json_body=None, ok=(200,), quiet=False):
    return api(method, f"{VALIDATOR_API}{path}", token, json_body, ok, quiet)


def ledger(method: str, path: str, token: str, json_body=None, ok=(200,), quiet=False):
    return api(method, f"{LEDGER_API}{path}", token, json_body, ok, quiet)


def read_party_id() -> str:
    if not PARTY_ID_FILE.exists():
        die("PARTY_ID.txt not found — run 02_create_party.py first")
    return PARTY_ID_FILE.read_text().strip()


def ensure_act_read_rights(token: str, party: str) -> None:
    """Grant our token's ledger user CanActAs/CanReadAs `party` (idempotent).

    The token's subject (e.g. validator-backend@clients) is the validator
    operator's ledger user, which holds ParticipantAdmin — so it may grant
    rights via the Ledger API user-management endpoints.
    """
    user_id = jwt_claims(token)["sub"]
    enc = urllib.parse.quote(user_id, safe="")
    status, data = ledger("GET", f"/v2/users/{enc}/rights", token, quiet=True)
    if status != 200:
        die(f"cannot list rights for user {user_id}: HTTP {status} {json.dumps(data)[:300]}")
    have_act = have_read = False
    for right in data.get("rights", []):
        kind = right.get("kind", {})
        if kind.get("CanActAs", {}).get("value", {}).get("party") == party:
            have_act = True
        if kind.get("CanReadAs", {}).get("value", {}).get("party") == party:
            have_read = True
    wanted = []
    if not have_act:
        wanted.append({"kind": {"CanActAs": {"value": {"party": party}}}})
    if not have_read:
        wanted.append({"kind": {"CanReadAs": {"value": {"party": party}}}})
    if not wanted:
        print(f"  user {user_id} already has actAs/readAs for the party")
        return
    status, data = ledger(
        "POST",
        f"/v2/users/{enc}/rights",
        token,
        {"userId": user_id, "rights": wanted, "identityProviderId": ""},
    )
    if status != 200:
        die(f"granting rights failed: HTTP {status} {json.dumps(data)[:400]}")
    print(f"  granted {len(wanted)} right(s) on {party} to user {user_id}")


def ledger_end_offset(token: str) -> int:
    status, data = ledger("GET", "/v2/state/ledger-end", token, quiet=True)
    if status != 200:
        die(f"ledger-end failed: HTTP {status} {json.dumps(data)[:300]}")
    return data["offset"]


def acs_holdings(token: str, party: str) -> list:
    """Active contracts implementing the token standard Holding interface.

    POST /v2/state/active-contracts with an InterfaceFilter and
    includeInterfaceView=true; returns dicts with contract id, template id and
    the decoded Holding view (owner, instrumentId, amount, lock, meta).
    """
    offset = ledger_end_offset(token)
    status, data = ledger(
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
                                    "InterfaceFilter": {
                                        "value": {
                                            "interfaceId": HOLDING_INTERFACE,
                                            "includeInterfaceView": True,
                                            "includeCreatedEventBlob": False,
                                        }
                                    }
                                }
                            }
                        ]
                    }
                },
                "verbose": False,
            },
        },
        quiet=True,
    )
    if status != 200:
        die(f"ACS holdings query failed: HTTP {status} {json.dumps(data)[:400]}")
    holdings = []
    for entry in data:
        contract = entry.get("contractEntry", {}).get("JsActiveContract")
        if not contract:
            continue
        created = contract["createdEvent"]
        for iview in created.get("interfaceViews", []):
            view = iview.get("viewValue")
            if view is None:
                continue
            holdings.append(
                {
                    "contract_id": created["contractId"],
                    "template_id": created["templateId"],
                    "instrument_id": view["instrumentId"]["id"],
                    "amount": view["amount"],
                    "locked": view.get("lock") is not None,
                    "view": view,
                }
            )
    return holdings


def submit_and_wait_for_transaction(token: str, commands: list, act_as: list,
                                    command_id: str, disclosed: list | None = None) -> dict:
    """POST /v2/commands/submit-and-wait-for-transaction (dies on non-200)."""
    body = {
        "commands": {
            "commands": commands,
            "commandId": command_id,
            "actAs": act_as,
            "readAs": act_as,
            "disclosedContracts": disclosed or [],
        }
    }
    status, data = ledger("POST", "/v2/commands/submit-and-wait-for-transaction", token, body)
    if status != 200:
        die(f"command submission failed: HTTP {status}")
    return data


def as_disclosed(contract_with_state: dict) -> dict:
    """Map a scan-proxy ContractWithState to a Ledger API DisclosedContract."""
    contract = contract_with_state["contract"]
    return {
        "templateId": contract["template_id"],
        "contractId": contract["contract_id"],
        "createdEventBlob": contract["created_event_blob"],
        "synchronizerId": contract_with_state.get("domain_id") or "",
    }
