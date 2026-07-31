"""OpenAI Responses API istemcisi.

Bu istemci yalnızca doğal Türkçe ifade üretimi ve bağımsız kalite
değerlendirmesi için kullanılır. Ground-truth tool çağrısı LLM'e bırakılmaz.

Paraphrase üretimi için varsayılan model ``gpt-4.1-mini``'dir. Judge görevleri
bu varsayılandan bağımsız olarak yapılandırmada ``gpt-5-mini`` seçer.

API anahtarı yalnızca ortam değişkeninden okunur; istek/yanıt metadata'sına,
provenance'a veya loglara kopyalanmaz. Responses API istekleri ayrıca veri
saklamayı ``store=False`` ile açıkça kapatır.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Mapping
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from toolcall_tr.llm.base import LLMMessage, LLMResponse

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_MODEL",
    "OpenAIClient",
    "OpenAINotInstalledError",
    "StructuredOutputError",
]

API_KEY_ENV = "OPENAI_API_KEY"
BASE_URL_ENV = "OPENAI_BASE_URL"

# Paraphrase üretim katmanı. Judge modeli bu varsayılandan bağımsız
# yapılandırılmalıdır (proje varsayılanı: gpt-5-mini).
DEFAULT_MODEL = "gpt-4.1-mini"

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high"]

_UNSUPPORTED_RE = re.compile(r"[Uu]nsupported (?:parameter|value): '([a-zA-Z_]+)'")
_SCHEMA_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _refusal_text(response: Any) -> str | None:
    """Responses API message içindeki refusal parçasını SDK sürümünden bağımsız bul."""
    for item in _field(response, "output") or ():
        candidates = [item, *(_field(item, "content") or ())]
        for candidate in candidates:
            if _field(candidate, "type") != "refusal":
                continue
            refusal = str(_field(candidate, "refusal") or "").strip()
            return refusal[:500] if refusal else "true"
    return None


class OpenAINotInstalledError(RuntimeError):
    """`openai` paketi kurulu değil."""

    def __init__(self) -> None:
        super().__init__(
            "openai paketi kurulu değil. Kurmak için: uv sync --extra openai\n"
            "Alternatif: şablon tabanlı üretici API anahtarı olmadan çalışır."
        )


class StructuredOutputError(ValueError):
    """Modelin yapılandırılmış çıktısı geçerli JSON veya istenen şema değil."""

    def __init__(self, message: str, *, response: LLMResponse | None = None) -> None:
        super().__init__(message)
        # Yanıt API'den geldikten sonra yerel ayrıştırma başarısız olabilir.
        # Bütçe katmanı bu alan sayesinde ücretlenmiş tokenları yine kaydeder.
        self.response = response


class OpenAIClient:
    """OpenAI Responses API istemcisi.

    ``reasoning_effort`` ve ``verbosity`` örnek ömrü boyunca varsayılan olarak
    saklanabilir; her çağrıda ayrıca geçersiz kılınabilir. ``safety_identifier``
    ham kullanıcı bilgisi değil, çağıranın oluşturduğu kararlı ve tercihen
    hash'lenmiş bir tanımlayıcı olmalıdır.
    """

    provider = "openai"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: Verbosity | None = None,
        safety_identifier: str | None = None,
        max_retries: int = 2,
        send_temperature: bool = True,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.safety_identifier = safety_identifier
        self._send_temperature = send_temperature

        if client is not None:
            self._client = client
            return

        try:
            import openai
        except ImportError as exc:  # pragma: no cover - opsiyonel bağımlılık
            raise OpenAINotInstalledError() from exc

        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise ValueError(
                f"{API_KEY_ENV} tanımlı değil. .env dosyasına ekleyin veya "
                "şablon tabanlı üreticiyi kullanın."
            )
        self._client = openai.OpenAI(
            api_key=key,
            base_url=base_url or os.environ.get(BASE_URL_ENV) or None,
            max_retries=max_retries,
        )

    def _payload(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
        *,
        reasoning_effort: ReasoningEffort | None,
        verbosity: Verbosity | None,
        safety_identifier: str | None,
        text_format: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": message.role, "content": message.content} for message in messages],
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if self._send_temperature:
            payload["temperature"] = temperature
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}

        text_options: dict[str, Any] = {}
        if verbosity is not None:
            text_options["verbosity"] = verbosity
        if text_format is not None:
            text_options["format"] = copy.deepcopy(dict(text_format))
        if text_options:
            payload["text"] = text_options

        if safety_identifier is not None:
            payload["safety_identifier"] = safety_identifier
        return payload

    def _adapt(self, error: Exception) -> bool:
        """Desteklenmeyen özel sıcaklığı bir kez kaldırıp yeniden dener."""
        match = _UNSUPPORTED_RE.search(str(error))
        if match is None or match.group(1) != "temperature" or not self._send_temperature:
            return False
        self._send_temperature = False
        return True

    def _create(self, payload: dict[str, Any]) -> Any:
        try:
            return self._client.responses.create(**payload)
        except Exception as exc:
            if not self._adapt(exc):
                raise
            payload.pop("temperature", None)
            return self._client.responses.create(**payload)

    def _to_response(self, response: Any) -> LLMResponse:
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None)
        reasoning_tokens = getattr(output_details, "reasoning_tokens", None)
        refusal = _refusal_text(response)

        metadata = {
            "api": "responses",
            "status": str(getattr(response, "status", "") or ""),
        }
        if incomplete_reason:
            metadata["incomplete_reason"] = str(incomplete_reason)
        if reasoning_tokens is not None:
            metadata["reasoning_tokens"] = str(reasoning_tokens)
        if refusal is not None:
            metadata["refusal"] = refusal

        return LLMResponse(
            text=str(getattr(response, "output_text", "") or "").strip(),
            model=self.model,
            provider=self.provider,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cached_input_tokens=getattr(input_details, "cached_tokens", None),
            metadata=metadata,
        )

    @staticmethod
    def _structured_status_error(result: LLMResponse) -> StructuredOutputError | None:
        """Eksik/refusal yanıtını belirsiz bir JSON hatasına dönüştürme."""
        status = result.metadata.get("status", "")
        incomplete_reason = result.metadata.get("incomplete_reason")
        refusal = result.metadata.get("refusal")

        if refusal is not None:
            return StructuredOutputError(
                f"structured output model tarafından reddedildi; status={status or 'bilinmiyor'}",
                response=result,
            )
        if status == "incomplete":
            detail = f"; neden={incomplete_reason}" if incomplete_reason else ""
            return StructuredOutputError(
                f"structured output tamamlanmadı; status=incomplete{detail}",
                response=result,
            )
        if status and status != "completed":
            return StructuredOutputError(
                f"structured output tamamlanmadı; status={status}",
                response=result,
            )
        if not result.text:
            status_detail = status or "bilinmiyor"
            return StructuredOutputError(
                f"structured output boş döndü; status={status_detail}",
                response=result,
            )
        return None

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int = 1024,
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: Verbosity | None = None,
        safety_identifier: str | None = None,
    ) -> LLMResponse:
        """Düz metin yanıtı üretir; mevcut ``LLMClient`` sözleşmesini korur."""
        payload = self._payload(
            messages,
            temperature,
            max_tokens,
            reasoning_effort=reasoning_effort or self.reasoning_effort,
            verbosity=verbosity or self.verbosity,
            safety_identifier=safety_identifier or self.safety_identifier,
        )
        return self._to_response(self._create(payload))

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        schema: Mapping[str, Any],
        schema_name: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: Verbosity | None = None,
        safety_identifier: str | None = None,
    ) -> LLMResponse:
        """Strict JSON Schema çıktısı üretir ve yanıtı yerelde de doğrular.

        API'nin ``strict=True`` garantisine ek olarak yerel doğrulama yapılır.
        Böylece proxy, uyumlu üçüncü taraf endpoint veya SDK sürüm farkları
        sessizce geçersiz ground-truth benzeri veri üretemez.
        """
        if not _SCHEMA_NAME_RE.fullmatch(schema_name):
            raise ValueError(
                "schema_name 1-64 karakter olmalı ve yalnızca harf, sayı, '_' veya '-' içermeli"
            )

        schema_copy = copy.deepcopy(dict(schema))
        try:
            Draft202012Validator.check_schema(schema_copy)
        except SchemaError as exc:
            raise ValueError(f"geçersiz JSON Schema: {exc.message}") from exc

        payload = self._payload(
            messages,
            temperature,
            max_tokens,
            reasoning_effort=reasoning_effort or self.reasoning_effort,
            verbosity=verbosity or self.verbosity,
            safety_identifier=safety_identifier or self.safety_identifier,
            text_format={
                "type": "json_schema",
                "name": schema_name,
                "schema": schema_copy,
                "strict": True,
            },
        )
        result = self._to_response(self._create(payload))
        status_error = self._structured_status_error(result)
        if status_error is not None:
            raise status_error
        try:
            parsed = json.loads(result.text)
            Draft202012Validator(schema_copy).validate(parsed)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(
                "model yanıtı geçerli JSON değil",
                response=result,
            ) from exc
        except ValidationError as exc:
            raise StructuredOutputError(
                f"model yanıtı JSON Schema ile uyuşmuyor: {exc.message}",
                response=result,
            ) from exc
        return result
