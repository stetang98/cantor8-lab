# Draft answers — Cantor8 Learner Bounty Google Form

Form: https://forms.gle/YMEr9rpZzq5fqxJDA
(Adapt to the exact field labels when opening the form; keep first person.)

**Name:** Ste Tang

**Contact (Telegram):** @Stetang

**GitHub / repo:** https://github.com/stetang98 (lab repo: `cantor8-lab`, can be pushed on request)

**PartyId (allocated internal party):**

```
stetang-c8lab-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f
```

**What I did (summary):**

I completed the "Touching the Ledger" lab end-to-end as reproducible Python
scripts (httpx only, numbered 01–05, all idempotent), using nothing but the
low-level APIs:

1. **Auth** — OAuth2 client_credentials against Keycloak realm `master`
   (client `hackathon`); one Bearer JWT (TTL 900s) works for both the
   Validator API and the JSON Ledger API (Canton 3.5.6).
2. **Internal party** — allocated via the Validator Admin API
   `POST /v0/admin/users`, cross-checked with `GET /v2/parties/{party}` on the
   Ledger API. PartyId above.
3. **TransferPreapproval** — granted my ledger user actAs rights via
   `POST /v2/users/{user}/rights`, then created the
   `Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal` contract
   with a raw CreateCommand (`POST /v2/commands/submit-and-wait-for-transaction`).
   The validator automation accepted it in ~6 seconds.
   Creation updateId: `1220cd6e25267acf43258916682f9ca43678e3e8fac36381aaf4547c27bc114487fd`
   Active TransferPreapproval cid: `007135023b2796c9233f70d07d98819a9d276cfc98e4dd421423efc40a7392e1f6ca...`
4. **Balance via ACS** — `POST /v2/state/active-contracts` at the ledger-end
   offset with an `InterfaceFilter` over
   `#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding`
   (`includeInterfaceView: true`), summing the view amounts.
   Current balance: **9.0 CC unlocked**.
5. **Stretch (transfer composition)** — the scan registry endpoint needed for
   the full Token Standard `TransferFactory_Transfer` is not reachable on this
   node (scan-proxy `/v0/scan-proxy/dso` 502s and no public scan host exists),
   so I composed the two on-ledger transactions by hand via raw
   ExerciseCommands with disclosed contracts instead:
   `AmuletRules_DevNet_Tap` (self-minted 10 CC to my party, updateId
   `12203e052afc9c8ad0de1bff7d14210518adeb8214c49cda6c2d890fa3f459e00447`)
   and `TransferPreapproval_Send` (1.0 CC from my party to the validator
   operator through its preapproval — the same settlement path the Token
   Standard factory uses for pre-approved receivers, updateId
   `1220c939264e40f026b85cebeb621dbe80f8f250099f992bc458a7356e53a9f40239`).

**Explorer link(s):**

No public scan/explorer is exposed for the dev.digik C8 network (verified via
DNS + certificate-transparency enumeration of cantor8.tech). All transactions
are pinned by updateId / offset / contract id (above and in the evidence
folder) and can be verified on the team's internal scan or via the C8 Wallet
(https://wallet.dev.digik.cantor8.tech). Happy to add explorer links if the
team shares a scan URL.

**Evidence:** `evidence/` folder in the repo — timestamped raw JSON responses
for every step (token claims, party allocation, proposal creation tx,
acceptance lookup, ACS balance snapshots, tap + transfer txs), plus NOTES.md
with every failure mode encountered (401 combos, wallet user_onboarded=false,
ACS 200-element cap, scan-proxy /dso 502).

**Still waiting on:** the team's Canton Coin drop to the PartyId above (lab
step 3) — it will appear as extra Holding contracts in my balance script.
