"""Ücretli LLM çağrıları için işlem başına sert bütçe kapısı."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from toolcall_tr.llm.base import LLMClient, LLMMessage, LLMResponse

__all__ = [
    "BudgetedLLMClient",
    "LLMBudgetExceededError",
    "LLMBudgetLimits",
    "LLMBudgetTracker",
]


class LLMBudgetExceededError(RuntimeError):
    """Yapılandırılmış ücretli çağrı veya token bütçesi aşıldı."""


@dataclass(frozen=True, slots=True)
class LLMBudgetLimits:
    """Tek bir CLI çalıştırması için üst sınırlar."""

    max_requests: int
    max_input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if self.max_requests < 1:
            raise ValueError("max_requests pozitif olmalı")
        if self.max_input_tokens < 1:
            raise ValueError("max_input_tokens pozitif olmalı")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens pozitif olmalı")


@dataclass(slots=True)
class LLMBudgetTracker:
    """Çağrıdan önce istek, çağrıdan sonra gerçek token bütçesini uygular."""

    limits: LLMBudgetLimits
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cached_requests: int = 0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def before_request(self) -> None:
        with self._lock:
            if self.requests >= self.limits.max_requests:
                raise LLMBudgetExceededError(
                    f"LLM istek bütçesi doldu: {self.requests}/{self.limits.max_requests}"
                )
            self.requests += 1

    def record(self, response: LLMResponse) -> None:
        with self._lock:
            self.input_tokens += response.input_tokens or 0
            self.output_tokens += response.output_tokens or 0
            self.cached_input_tokens += response.cached_input_tokens or 0
            self.cached_requests += int(response.cached)

            if self.input_tokens > self.limits.max_input_tokens:
                raise LLMBudgetExceededError(
                    "LLM girdi token bütçesi aşıldı: "
                    f"{self.input_tokens}/{self.limits.max_input_tokens}"
                )
            if self.output_tokens > self.limits.max_output_tokens:
                raise LLMBudgetExceededError(
                    "LLM çıktı token bütçesi aşıldı: "
                    f"{self.output_tokens}/{self.limits.max_output_tokens}"
                )

    def report(self) -> dict[str, int]:
        with self._lock:
            return {
                "requests": self.requests,
                "cached_requests": self.cached_requests,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cached_input_tokens": self.cached_input_tokens,
                "max_requests": self.limits.max_requests,
                "max_input_tokens": self.limits.max_input_tokens,
                "max_output_tokens": self.limits.max_output_tokens,
            }


class BudgetedLLMClient:
    """Her canlı çağrıyı ortak işlem bütçesinden geçiren istemci sarmalayıcısı."""

    def __init__(self, client: LLMClient, tracker: LLMBudgetTracker) -> None:
        self._client = client
        self._tracker = tracker
        self.provider = client.provider
        self.model = client.model

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self._tracker.before_request()
        response = self._client.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._tracker.record(response)
        return response

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        schema: Mapping[str, Any],
        schema_name: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        complete_json = getattr(self._client, "complete_json", None)
        if not callable(complete_json):
            raise TypeError(f"{self.provider}:{self.model} structured output desteklemiyor")
        self._tracker.before_request()
        try:
            response: LLMResponse = complete_json(
                messages,
                schema=schema,
                schema_name=schema_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            # Sağlayıcı yanıt verdikten sonra yerel JSON/şema doğrulaması
            # başarısız olmuşsa çağrı yine ücretlenmiştir. İstemci hataya yanıtı
            # eklediğinde gerçek kullanımı kaydet ve özgün hatayı koru.
            failed_response = getattr(exc, "response", None)
            if isinstance(failed_response, LLMResponse):
                self._tracker.record(failed_response)
            raise
        self._tracker.record(response)
        return response
