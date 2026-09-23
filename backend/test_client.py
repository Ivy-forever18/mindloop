from evomap_client import EvoMapClient, _pkce_challenge


def test_pkce_challenge_matches_rfc_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert _pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_authorization_url_is_s256():
    client = EvoMapClient(
        base_url="https://evomap.ai",
        client_id="evm_client_test_example",
        client_secret="secret",
        redirect_uri="http://localhost:8000/oauth/callback",
        scopes="recipe:read",
    )
    url, attempt = client.build_authorization_url()
    assert "code_challenge_method=S256" in url
    assert "recipe%3Aread" in url
    assert attempt.state
    assert attempt.verifier
