import unittest

from evomap_client import EvoMapClient, _pkce_challenge
from llm_client import LLMError, OpenAICompatibleClient


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


class RetryClient(OpenAICompatibleClient):
    def __init__(self):
        super().__init__(base_url="https://example.test/v1", api_key="test", model="test", max_retries=1)
        self.calls = 0

    async def _request(self, request_body):
        self.calls += 1
        if self.calls == 1:
            raise LLMError("timeout", code="timeout", retryable=True)
        return {"ok": True}


class LLMClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_retries_once(self):
        client = RetryClient()
        result = await client.json_completion(system_prompt="test", payload={})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.calls, 2)
