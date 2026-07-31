"""Anthropic Claude istemcisi.

İsteğe bağlı bağımlılık: ``uv sync --extra anthropic``. Bu istemci olmadan da
tüm boru hattı çalışır -- şablon tabanlı üretici API anahtarı istemez.

API anahtarı **yalnızca** ortam değişkeninden okunur ve hiçbir yere yazılmaz:
ne cassette'e, ne loga, ne provenance'a. Kimlik bilgisi execution altyapısına
aittir, veriye değil.
"""

from __future__ import annotations

import os
from typing import Any

from toolcall_tr.llm.base import LLMMessage, LLMResponse

__all__ = ["API_KEY_ENV", "AnthropicClient", "AnthropicNotInstalledError"]

API_KEY_ENV = "ANTHROPIC_API_KEY"

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicNotInstalledError(RuntimeError):
    """`anthropic` paketi kurulu değil."""

    def __init__(self) -> None:
        super().__init__(
            "anthropic paketi kurulu değil. Kurmak için: uv sync --extra anthropic\n"
            "Alternatif: şablon tabanlı üretici API anahtarı olmadan çalışır."
        )


class AnthropicClient:
    """Claude Messages API istemcisi."""

    provider = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
            return

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - opsiyonel bağımlılık
            raise AnthropicNotInstalledError() from exc

        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise ValueError(
                f"{API_KEY_ENV} tanımlı değil. .env dosyasına ekleyin veya "
                "şablon tabanlı üreticiyi kullanın."
            )
        self._client = anthropic.Anthropic(api_key=key)

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=turns,
        )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text.strip(),
            model=self.model,
            provider=self.provider,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
