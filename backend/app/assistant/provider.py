"""Where an answer comes from.

Three providers behind one interface. The demo provider writes the answer itself from the
claim and needs nothing outside the machine; the two model providers send the same grounded
context to a model and are used only when a key is configured. Whatever answers, the guard
checks the result, so no provider can say more than the claim supports.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.assistant import intents
from app.assistant.context import ClaimContext
from app.config import get_settings

logger = logging.getLogger("claimai.assistant")

SYSTEM_PROMPT = """You are the documentation assistant of a claim pre-submission tool.

Answer only from the claim context below.
If the context does not contain the answer, say that the claim does not show it.
Never invent a document, a page, a value or a clinical fact.
Never diagnose the patient or judge whether treatment was necessary.
Never call anything fraud, forgery or fake.
Never say a claim is approved, ready for submission or medically necessary.
Never say that human review is unnecessary.

Cite what you rely on with markers taken from the context ids:
[[document:<id>]] [[finding:<id>]] [[requirement:<key>]] [[question:<id>]]
Use at most six citations. Write three short paragraphs at most, in plain British English.
"""


class ProviderError(RuntimeError):
    """The provider could not produce an answer."""


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    model: str
    mode: str
    api_key_configured: bool

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "mode": self.mode,
            "api_key_configured": self.api_key_configured,
        }


class Provider:
    """What every provider offers."""

    name = "provider"
    mode = "unknown"

    @property
    def model(self) -> str:
        return get_settings().effective_llm_model

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.model, self.mode, get_settings().llm_api_key_configured)

    def answer(self, question: str, intent: str, context: ClaimContext) -> str:
        raise NotImplementedError


class DemoProvider(Provider):
    """Writes the answer from the claim itself, the same way every time.

    This is not a language model and is not presented as one: it selects a template for the
    intent and fills it from the claim, so the demo works with no key and no network.
    """

    name = "demo"
    mode = "offline-deterministic"

    def answer(self, question: str, intent: str, context: ClaimContext) -> str:
        return intents.compose(intent, context)


class AnthropicProvider(Provider):
    """Anthropic Messages API."""

    name = "anthropic"
    mode = "api"
    endpoint = "https://api.anthropic.com/v1/messages"
    version = "2023-06-01"

    def answer(self, question: str, intent: str, context: ClaimContext) -> str:
        settings = get_settings()
        key = settings.anthropic_api_key.get_secret_value()
        if not key:
            raise ProviderError("No Anthropic API key is configured.")
        payload = {
            "model": self.model,
            "max_tokens": 700,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": intents.prompt(question, intent, context)}],
        }
        body = _post(
            self.endpoint,
            payload,
            {"x-api-key": key, "anthropic-version": self.version},
        )
        parts = [block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"]
        text = "\n".join(part for part in parts if part).strip()
        if not text:
            raise ProviderError("The model returned no text.")
        return text


class OpenAICompatibleProvider(Provider):
    """Any OpenAI-compatible chat completions endpoint."""

    name = "openai"
    mode = "api"

    def answer(self, question: str, intent: str, context: ClaimContext) -> str:
        settings = get_settings()
        key = settings.openai_api_key.get_secret_value()
        if not key:
            raise ProviderError("No OpenAI-compatible API key is configured.")
        if not self.model:
            raise ProviderError("No model is configured for the OpenAI-compatible provider.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": intents.prompt(question, intent, context)},
            ],
            "temperature": 0,
        }
        url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        body = _post(url, payload, {"Authorization": f"Bearer {key}"})
        choices = body.get("choices") or []
        text = (choices[0].get("message", {}).get("content") if choices else "") or ""
        if not text.strip():
            raise ProviderError("The model returned no text.")
        return text.strip()


def _post(url: str, payload: dict, headers: dict[str, str], timeout: float = 30.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:  # pragma: no cover - needs a configured key
        raise ProviderError(f"The model provider answered {exc.code}.") from exc
    except OSError as exc:  # pragma: no cover - needs a configured key
        raise ProviderError("The model provider could not be reached.") from exc


PROVIDERS: dict[str, type[Provider]] = {
    "demo": DemoProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAICompatibleProvider,
}


def get_provider() -> Provider:
    """The configured provider, or the deterministic one when no key is available.

    A provider that needs a key it does not have is never selected: the demo answers instead,
    and says so.
    """
    settings = get_settings()
    chosen = PROVIDERS.get(settings.llm_provider, DemoProvider)
    if chosen is not DemoProvider and not settings.llm_api_key_configured:
        logger.info("No API key for %s; answering with the deterministic demo provider", settings.llm_provider)
        return DemoProvider()
    return chosen()
