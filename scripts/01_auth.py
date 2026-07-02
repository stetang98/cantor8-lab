"""Step 1a — authenticate against the C8 DevNet IdP (Keycloak, realm `master`).

Obtains a Bearer JWT via the OAuth2 client_credentials grant and smoke-tests it
against both the JSON Ledger API (GET /v2/version) and the Validator API
(GET /v0/validator-user). Saves decoded claims + probe results as evidence.
"""

import common as c


def main() -> None:
    print(f"POST {c.AUTH_URL} (client_credentials, client_id={c.CLIENT_ID})")
    token = c.get_token()
    claims = c.jwt_claims(token)
    print(f"  token OK ({len(token)} chars), expires in {claims['exp'] - claims['iat']}s")
    print(f"  sub={claims.get('sub')}  azp={claims.get('azp')}")
    print(f"  aud={claims.get('aud')}")
    print(f"  scope={claims.get('scope')}")

    print("Smoke test: JSON Ledger API")
    ledger_status, version = c.ledger("GET", "/v2/version", token)

    print("Smoke test: Validator API (public validator info)")
    validator_status, vinfo = c.validator("GET", "/v0/validator-user", token)

    c.save_evidence(
        "01-auth",
        {
            "token_endpoint": c.AUTH_URL,
            "client_id": c.CLIENT_ID,
            "grant_type": "client_credentials",
            "access_token_prefix": token[:40] + "...(redacted, expires in 900s)",
            "decoded_claims": claims,
            "ledger_api_version_probe": {"status": ledger_status, "body": version},
            "validator_user_probe": {"status": validator_status, "body": vinfo},
        },
    )
    if ledger_status != 200 or validator_status != 200:
        c.die("one of the smoke tests failed — see evidence file")
    print("AUTH OK — same Bearer token is valid for both Ledger API and Validator API.")


if __name__ == "__main__":
    main()
