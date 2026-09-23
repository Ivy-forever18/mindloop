from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


class EvoMapError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(f"EvoMap returned HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OAuthAttempt:
    state: str
    verifier: str


class EvoMapClient:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.token = token or None

    @property
    def is_test_mode(self) -> bool:
        return self.client_id.startswith("evm_client_test_")

    def build_authorization_url(self) -> tuple[str, OAuthAttempt]:
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{self.base_url}/oauth/authorize?{urlencode(params)}", OAuthAttempt(
            state=state,
            verifier=verifier,
        )

    async def exchange_code(self, *, code: str, verifier: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": verifier,
                },
            )
        data = self._json_or_text(response)
        if response.is_error:
            raise EvoMapError(response.status_code, data)
        self.token = data["access_token"]
        return data

    async def search_recipes(self, query: str, limit: int = 5) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/developer/oauth/recipes",
            params={"q": query, "limit": limit},
        )

    async def list_genes(self, *, gene_type: str | None, limit: int = 5) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if gene_type:
            params["type"] = gene_type
        return await self._request("GET", "/developer/oauth/genes", params=params)

    async def query_reuse(
        self,
        *,
        recipe_id: str | None,
        asset_id: str | None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if bool(recipe_id) == bool(asset_id):
            raise ValueError("Pass exactly one of recipe_id or asset_id")
        params = {
            "limit": limit,
            **({"recipe_id": recipe_id} if recipe_id else {"asset_id": asset_id}),
        }
        return await self._request("GET", "/developer/oauth/reuse", params=params)

    async def create_recipe_draft(
        self, payload: dict[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/developer/oauth/recipe",
            json=payload,
            extra_headers={"Idempotency-Key": idempotency_key},
        )

    async def publish_recipe_test_mode(
        self, payload: dict[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]:
        if not self.is_test_mode:
            raise ValueError("Publishing is restricted to an evm_client_test_ credential")
        return await self._request(
            "POST",
            "/developer/oauth/recipe/publish",
            json=payload,
            extra_headers={"Idempotency-Key": idempotency_key},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise EvoMapError(401, "No access token. Visit /oauth/start first.")
        headers = {"Authorization": f"Bearer {self.token}"}
        headers.update(extra_headers or {})
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers=headers,
            )
        data = self._json_or_text(response)
        if response.is_error:
            raise EvoMapError(response.status_code, data)
        return data

    @staticmethod
    def _json_or_text(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"message": response.text}
