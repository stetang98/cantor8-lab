# NOTES — precise log of what worked, what failed, and why

Network: C8 Canton DevNet (Cantor8's own network — own DSO
`DSO::1220be58c29e65de40bf273be1dc2b266d43a9a002ea5b18955aeef7aac881bb471a`,
synchronizer `global-domain::1220be58...` — NOT the global Canton DevNet).
Participant: Canton **3.5.6** (from `GET /v2/version`). Splice DARs deployed
(package ids in evidence, e.g. TransferPreapproval pkg `23f47481dab6...`).

## Auth (Keycloak)

| Attempt | Result |
|---|---|
| `GET /realms/master/.well-known/openid-configuration` | 200 (realm exists) |
| `GET /realms/hackathon/.well-known/...` | 404 (no such realm) |
| client_credentials, `client_id=hackathon`, `client_secret=0JEl...` | **200 — WORKS** |
| client_credentials, `client_id=hackathon`, no secret | 401 `unauthorized_client` |

Winning combo: realm `master`, `client_id=hackathon`, secret from the doc.
Token TTL **900s** (scripts fetch a fresh one per run). Decoded claims:
`sub=validator-backend@clients` — i.e. the token IS the validator operator's
own ledger user (confirmed: `GET /v0/validator-user` returns
`user_name=validator-backend@clients`). It therefore has validator-admin
rights on the Validator API and **ParticipantAdmin** on the Ledger API.
`aud` covers both APIs; one token works for everything.

## Step 1 — internal party (DONE)

- `POST /api/validator/v0/admin/users` `{"name":"stetang-c8lab-1"}` → 200:
  `stetang-c8lab-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f`
  (allocates the internal party AND installs the wallet/WalletAppInstall for it).
- Cross-checked at Ledger API level: `GET /v2/parties/{party}` → 200.
- The task doc's note about `/v0/admin/external-party/topology/{generate,submit}`
  applies to EXTERNAL (locally-signed) parties only; for an INTERNAL party the
  admin-users route is the correct low-level path. `setup-proposal` was never touched.
- Script is idempotent: if the user exists it resolves the party via `GET /v2/users/{id}`.

## Step 2 — TransferPreapproval (DONE)

1. Granted our ledger user `CanActAs`/`CanReadAs` on the new party via
   `POST /v2/users/validator-backend%40clients/rights` (works because the user
   is ParticipantAdmin). Low-level user-management, no validator magic.
2. Raw `CreateCommand` via `POST /v2/commands/submit-and-wait-for-transaction`:
   - template `#splice-wallet:Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal`
   - args `{receiver: <our party>, provider: <validator party>, expectedDso: <DSO>}`
   - provider = `cantor8-digik-1::12204e94...` (from `/v0/validator-user`),
     DSO from `/v0/scan-proxy/dso-party-id`.
   - **updateId `1220cd6e25267acf43258916682f9ca43678e3e8fac36381aaf4547c27bc114487fd`**,
     offset 2217907, proposal cid `00750f9be7...`.
3. Validator automation exercised `TransferPreapprovalProposal_Accept` within ~6s
   (provider pays the preapproval fee). Active contract confirmed BOTH via ACS
   (template filter) and `GET /v0/scan-proxy/transfer-preapprovals/by-party/{party}`:
   `TransferPreapproval` cid `007135023b2796c9233f70d07d98819a9d276cfc98e4dd421423efc40a7392e1f6...`.

## Step 3 — Canton Coin from the team (USER ACTION)

Post this PartyId in the hackathon group so the team can send CC:

```
stetang-c8lab-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f
```

Note: the party already holds 9 CC from the DevNet self-tap (step 5), so the
balance will be non-zero even before the team's transfer; the team's CC will
show up as additional Holding contracts in `04_balance.py`.

## Step 4 — balance via ACS / Holding interface (DONE)

- `GET /v2/state/ledger-end` → offset, then `POST /v2/state/active-contracts`
  with `InterfaceFilter` on
  `#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding`,
  `includeInterfaceView: true`; summed interface-view `amount`s.
- Result after step 5: **9.0 CC unlocked, 1 Holding contract**.
- Gotcha found: the unary ACS endpoint hard-caps at 200 elements — pointing it
  at the validator party (201+ holdings) returns HTTP 413
  `JSON_API_MAXIMUM_LIST_ELEMENTS_NUMBER_REACHED`. Not an issue for our party.

## Step 5 — compose a transfer (DONE, with one documented substitution)

Blocked paths (and why):

- Wallet API (`/v0/wallet/tap`, `/v2/wallet/token-standard/transfers`):
  `GET /v0/wallet/user-status` for our token → `user_onboarded=false`. The
  operator's wallet runs under ledger user `OPERATOR_WALLET_USER_ID`, and the
  Keycloak client_credentials `sub` is fixed — we can never appear as that
  user. So no wallet endpoints with the hackathon token.
- Full Token Standard round trip (`TransferFactory_Transfer`): requires the
  registry endpoint `POST /registry/transfer-instruction/v1/transfer-factory`
  served by a SCAN app. The validator's scan-proxy does not forward registry
  routes; `GET /v0/scan-proxy/dso` (which carries the SV scan URLs) returns
  **HTTP 502 consistently**; DNS + crt.sh sweep of `*.cantor8.tech` shows no
  public scan/SV host. → registry unreachable from outside.

What was composed instead — 100% low-level JSON Ledger API `ExerciseCommand`s:

1. **`AmuletRules_DevNet_Tap`** (DevNet faucet choice, `controller receiver` —
   our own party; touches nobody else's funds). Disclosed contracts:
   AmuletRules + OpenMiningRound #51072 (contract ids + `created_event_blob`s
   from scan-proxy). Minted 10 CC.
   updateId `12203e052afc9c8ad0de1bff7d14210518adeb8214c49cda6c2d890fa3f459e00447`.
2. **`TransferPreapproval_Send`** on the VALIDATOR party's own preapproval
   contract, `sender = our party` (controller sender), hand-built
   `PaymentTransferContext` (`{amuletRules, context: {openMiningRound,
   issuingMiningRounds: [], validatorRights: [], featuredAppRight: null}}`),
   inputs `[InputAmulet <our tapped amulet>]`, 3 disclosed contracts.
   Sent 1.0 CC our party → validator operator.
   **updateId `1220c939264e40f026b85cebeb621dbe80f8f250099f992bc458a7356e53a9f40239`**, offset 2217993.
   This is the same preapproval settlement path the Token Standard
   TransferFactory delegates to for pre-approved receivers.

## Explorer

No public scan/explorer exists for this network (checked: `scan|explorer|sv|app
.dev.digik.cantor8.tech` unresolvable; crt.sh enumeration of every issued
`cantor8.tech` cert shows only validator/wallet/keycloak hosts). The C8 Wallet
UI (`https://wallet.dev.digik.cantor8.tech`, prod `https://wallet.cantor8.tech`)
is the user-facing view. All transactions are pinned by updateId + offset +
contract id in `evidence/` so the team can verify them on their internal scan.

## Open items for the user

1. Post the PartyId (above) in the hackathon group → team sends CC (step 3).
2. Ask the team whether a scan UI / scan API URL exists for `dev.digik` — if
   yes, `05_token_transfer.py` can be extended to the full
   `TransferFactory_Transfer` registry round trip, and explorer links can be
   added to the form answers.
