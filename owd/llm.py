"""Free language models with fallback: Gemini (Google AI Studio), OpenRouter's :free models and
Cloudflare Workers AI, tried in the order set in channel.toml.

`complete_json` sends one prompt and returns parsed JSON. A model that is rate limited, errors,
times out or returns unusable JSON is skipped for the next one. Keys never appear in errors or logs.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from owd.env import load_dotenv

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CLOUDFLARE_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions"
TIMEOUT = httpx.Timeout(30.0, read=600.0)  # free Gemini Flash can take minutes when queued
STOP_STATUSES = {401, 402, 403}  # the key or account is the problem: skip the whole provider
RETRY_STATUSES = {500, 502, 503, 504}  # the model is busy: wait and try it once more
RETRY_WAIT = 20.0


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Model:
    provider: str  # gemini | openrouter | cloudflare
    name: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.name}"


@dataclass
class Reply:
    data: dict
    model: Model
    attempts: list[str] = field(default_factory=list)  # what failed before this one, for the log


def extract_json(text: str) -> dict:
    """The JSON object in a model's answer, ignoring ``` fences or chatter around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("the reply is not a JSON object")
    return value


def models_from_settings(settings: dict) -> list[Model]:
    """Models in the order channel.toml lists them: providers in the order they appear, each
    provider's models in its own order."""
    llm = settings.get("llm", {})
    return [Model(provider, name) for provider, names in llm.items()
            if provider in ("gemini", "openrouter", "cloudflare") for name in names]


class LLM:
    def __init__(
        self,
        models: list[Model],
        *,
        http: httpx.Client | None = None,
        env: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda message: None,
    ):
        if env is None:
            load_dotenv()
            env = dict(os.environ)
        self.env = env
        self.models = [m for m in models if self._key_for(m.provider)]
        self.http = http or httpx.Client(timeout=TIMEOUT)
        self.sleep, self.log = sleep, log
        self._dead_providers: set[str] = set()

    def _key_for(self, provider: str) -> str | None:
        name = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "cloudflare": "CLOUDFLARE_AI_TOKEN"}[provider]
        value = (self.env.get(name) or "").strip()
        if provider == "cloudflare" and not (self.env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip():
            return None
        return value or None

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        validate: Callable[[dict], None] = lambda data: None,
        temperature: float = 0.8,
        max_tokens: int = 16_000,
    ) -> Reply:
        """Ask each model in turn until one returns JSON that passes `validate` (which raises
        ValueError to reject it)."""
        if not self.models:
            raise LLMError("No language model is configured: add GEMINI_API_KEY or OPENROUTER_API_KEY")
        attempts: list[str] = []
        for model in self.models:
            if model.provider in self._dead_providers:
                continue
            started = time.perf_counter()
            try:
                text = self._call(model, system, user, temperature, max_tokens)
                data = extract_json(text)
                validate(data)
            except _ProviderDown as error:
                self._dead_providers.add(model.provider)
                attempts.append(f"{model.label}: {error}")
                self.log(f"{model.label}: {error}; skipping {model.provider}")
                continue
            except (LLMError, ValueError, httpx.HTTPError) as error:
                reason = type(error).__name__ if isinstance(error, httpx.HTTPError) else str(error)
                attempts.append(f"{model.label}: {reason[:200]}")
                self.log(f"{model.label}: {reason[:200]}")
                continue
            self.log(f"{model.label}: answered in {time.perf_counter() - started:.0f}s")
            return Reply(data, model, attempts)
        raise LLMError("Every model failed: " + " | ".join(attempts))

    def _call(self, model: Model, system: str, user: str, temperature: float, max_tokens: int) -> str:
        if model.provider == "gemini":
            return self._gemini(model.name, system, user, temperature, max_tokens)
        return self._chat(model, system, user, temperature, max_tokens)

    def _post(self, url: str, *, headers: dict, payload: dict) -> dict:
        for attempt in range(2):
            response = self.http.post(url, headers=headers, json=payload)
            if response.status_code in RETRY_STATUSES and attempt == 0:
                self.log(f"HTTP {response.status_code} (busy); trying again in {RETRY_WAIT:.0f}s")
                self.sleep(RETRY_WAIT)  # free models are often briefly overloaded
                continue
            break
        if response.status_code in STOP_STATUSES:
            raise _ProviderDown(f"HTTP {response.status_code} (check the key and its permissions)")
        if response.status_code == 429:
            raise LLMError("rate limited (HTTP 429)")
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {' '.join(response.text.split())[:200]}")
        return response.json()

    def _gemini(self, name: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
        body = self._post(
            GEMINI_URL.format(model=name),
            headers={"x-goog-api-key": self._key_for("gemini")},
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            },
        )
        candidates = body.get("candidates") or []
        if not candidates:
            raise LLMError(f"no answer ({body.get('promptFeedback', {}).get('blockReason', 'empty')})")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise LLMError("the answer was cut off (MAX_TOKENS)")
        if not text.strip():
            raise LLMError(f"empty answer ({candidate.get('finishReason')})")
        return text

    def _chat(self, model: Model, system: str, user: str, temperature: float, max_tokens: int) -> str:
        if model.provider == "openrouter":
            url = OPENROUTER_URL
            headers = {"Authorization": f"Bearer {self._key_for('openrouter')}", "X-Title": "Old Wisdom Decoded"}
        else:
            url = CLOUDFLARE_URL.format(account=self.env["CLOUDFLARE_ACCOUNT_ID"].strip())
            headers = {"Authorization": f"Bearer {self._key_for('cloudflare')}"}
        body = self._post(
            url,
            headers=headers,
            payload={
                "model": model.name,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        if body.get("error"):
            raise LLMError(f"provider error: {' '.join(str(body['error']).split())[:200]}")
        choices = body.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
        if choices and choices[0].get("finish_reason") == "length":
            raise LLMError("the answer was cut off (length)")
        if not text.strip():
            raise LLMError("empty answer")
        return text


class _ProviderDown(LLMError):
    pass
