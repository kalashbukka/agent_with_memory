"""Groq chat-completions client (used only to generate the incident analysis)."""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# On 429, wait for Groq's retry-after (if short) and retry, instead of failing the request.
MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 15.0


class GroqError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def chat_json(system: str, user: str) -> dict[str, Any]:
    """Call Groq in JSON mode and return the parsed JSON object."""
    s = get_settings()
    if not s.groq_api_key:
        raise GroqError("GROQ_API_KEY is not configured on the server.", 503)
    if not s.groq_model:
        raise GroqError("GROQ_MODEL is not configured on the server.", 503)

    body: dict[str, Any] = {
        "model": s.groq_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {s.groq_api_key}"}

    async with httpx.AsyncClient(timeout=s.groq_timeout_seconds) as http:
        try:
            for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                resp = await http.post(GROQ_URL, json=body, headers=headers)
                if resp.status_code == 400 and "response_format" in resp.text:
                    # Model does not support JSON mode: retry without it and parse the text.
                    body.pop("response_format")
                    resp = await http.post(GROQ_URL, json=body, headers=headers)
                wait = _retry_after(resp)
                if resp.status_code != 429 or wait is None or attempt == MAX_RATE_LIMIT_RETRIES:
                    break
                log.info("Groq rate limited; retrying in %.1fs", wait)
                await asyncio.sleep(wait)
        except httpx.TimeoutException as exc:
            raise GroqError(f"Groq request timed out after {s.groq_timeout_seconds:.0f}s.", 504) from exc
        except httpx.HTTPError as exc:
            raise GroqError(f"Groq is unavailable: {type(exc).__name__}", 503) from exc

    if resp.status_code == 429:
        retry = resp.headers.get("retry-after")
        raise GroqError(f"Groq rate limit reached{f', retry after {retry}s' if retry else ''}.", 429)
    if resp.status_code in (401, 403):
        raise GroqError("Groq authentication failed - check GROQ_API_KEY.", 502)
    if resp.status_code >= 400:
        detail = _error_message(resp)
        raise GroqError(f"Groq API error {resp.status_code}: {detail}", 502)

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GroqError("Groq returned an unexpected response shape.") from exc
    return _parse_json(content)


def _retry_after(resp: httpx.Response) -> float | None:
    """Seconds to wait before retrying a 429, if Groq says and it's short enough to wait for."""
    try:
        wait = float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None
    return wait if 0 <= wait <= MAX_RETRY_WAIT_SECONDS else None


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"][:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]


def _parse_json(content: str | None) -> dict[str, Any]:
    if not content:
        raise GroqError("Groq returned an empty response.")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise GroqError("Groq response did not contain JSON.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GroqError("Groq returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise GroqError("Groq returned JSON that is not an object.")
    return data
