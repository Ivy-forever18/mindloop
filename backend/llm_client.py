from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


class LLMError(RuntimeError):
    def __init__(self, message: str, *, code: str = "gateway_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OpenAICompatibleClient:
    """Small OpenAI-compatible client with one safe transient-error retry."""

    def __init__(
        self, *, base_url: str, api_key: str, model: str,
        timeout_seconds: float = 40, max_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def json_completion(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise LLMError("AI gateway is not configured", code="not_configured")
        request_body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        last_error: LLMError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._request(request_body)
            except LLMError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                await asyncio.sleep(0.35 * (attempt + 1))
        raise last_error or LLMError("AI gateway request failed")

    async def _request(self, request_body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=request_body,
                )
        except httpx.TimeoutException as exc:
            raise LLMError("AI gateway timed out", code="timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"AI gateway request failed: {type(exc).__name__}",
                code="network_error", retryable=True,
            ) from exc
        if response.is_error:
            request_id = response.headers.get("x-request-id", "unknown")
            retryable = response.status_code == 429 or response.status_code >= 500
            raise LLMError(
                f"AI gateway returned HTTP {response.status_code} (request_id={request_id})",
                code=f"http_{response.status_code}", retryable=retryable,
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return json.loads(self._strip_code_fence(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("AI gateway returned invalid JSON", code="invalid_json", retryable=True) from exc

    @staticmethod
    def _strip_code_fence(value: str) -> str:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text
