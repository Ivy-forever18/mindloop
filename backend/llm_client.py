from __future__ import annotations

import json
from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Small OpenAI-compatible client for the EvoMap model gateway."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def json_completion(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise LLMError("AI gateway is not configured")
        request_body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=request_body,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"AI gateway request failed: {type(exc).__name__}") from exc
        if response.is_error:
            request_id = response.headers.get("x-request-id", "unknown")
            raise LLMError(f"AI gateway returned HTTP {response.status_code} (request_id={request_id})")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return json.loads(self._strip_code_fence(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("AI gateway returned an invalid JSON response") from exc

    @staticmethod
    def _strip_code_fence(value: str) -> str:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text
