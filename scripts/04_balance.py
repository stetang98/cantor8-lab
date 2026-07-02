"""Step 4 — check the party's balance by indexing the Active Contracts Set.

Pure Ledger API flow, exactly as the lab asks:
  1. GET /v2/state/ledger-end for the current offset.
  2. POST /v2/state/active-contracts with an InterfaceFilter over the token
     standard Holding interface
       #splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding
     with includeInterfaceView=true.
  3. Sum the interface-view `amount`s (grouped by instrument, locked/unlocked).

Optionally pass a party id as argv[1]; defaults to PARTY_ID.txt.
"""

import sys
from collections import defaultdict
from decimal import Decimal

import common as c


def main() -> None:
    party = sys.argv[1] if len(sys.argv) > 1 else c.read_party_id()
    token = c.get_token()
    print(f"Indexing ACS over Holding interface for party:\n  {party}")
    c.ensure_act_read_rights(token, party)
    print(f"  interface filter: {c.HOLDING_INTERFACE}")

    holdings = c.acs_holdings(token, party)
    totals = defaultdict(lambda: {"unlocked": Decimal(0), "locked": Decimal(0), "contracts": 0})
    for h in holdings:
        bucket = "locked" if h["locked"] else "unlocked"
        totals[h["instrument_id"]][bucket] += Decimal(h["amount"])
        totals[h["instrument_id"]]["contracts"] += 1

    print(f"\n{len(holdings)} Holding contract(s) in the ACS for this party")
    for h in holdings:
        flag = "LOCKED" if h["locked"] else "unlocked"
        print(f"  {h['amount']:>24} {h['instrument_id']:<6} {flag:<8} cid={h['contract_id'][:32]}...")
    if not holdings:
        print("  (no holdings yet — balance is 0)")

    print("\nBALANCE SUMMARY")
    for instrument, t in totals.items():
        print(f"  {instrument}: unlocked={t['unlocked']} locked={t['locked']} "
              f"across {t['contracts']} contract(s)")

    c.save_evidence(
        "04-balance-acs",
        {
            "party": party,
            "holding_interface": c.HOLDING_INTERFACE,
            "holdings": holdings,
            "totals": {
                k: {"unlocked": str(v["unlocked"]), "locked": str(v["locked"]),
                    "contracts": v["contracts"]}
                for k, v in totals.items()
            },
        },
    )


if __name__ == "__main__":
    main()
