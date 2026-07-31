"""Executor'lar — tool çağrısını gerçekten çalıştıran katman.

Executor'lar **cassette'ten habersizdir**: kendilerine verilen ``httpx.Client``'ı
kullanırlar. Kayıt/oynatma bir taşıma katmanı detayıdır. Bu ayrım sayesinde
M2'nin in-process ASGI mock'u aynı executor arayüzüne oturur.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from toolcall_tr.canonical import sha256_hex
from toolcall_tr.execution.cassette import CassetteMissError, CassetteTransport
from toolcall_tr.models import ExecutionClass, StepOutcome, ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolExecutionError
from toolcall_tr.schema import ArgumentError, normalize_arguments, validate_arguments

__all__ = ["ExecutionResult", "Executor", "ReadOnlyHTTPExecutor"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Tek bir çalıştırmanın sonucu.

    ``outcome`` burada **beklentiden bağımsızdır**: executor "başarılı mı?"
    sorusunu cevaplar, "beklenen bu muydu?" sorusunu runner cevaplar. Bir 404,
    executor için hatadır ama plan onu bekliyorsa ground-truth'un kendisidir.
    """

    tool_id: str
    execution_class: ExecutionClass
    arguments: dict[str, Any]
    outcome: StepOutcome
    status_code: int | None = None
    response: Any = None
    error: str | None = None
    cassette_key: str | None = None
    raw_response_hash: str | None = None
    latency_ms: float | None = None
    state_hash_before: str | None = None
    state_hash_after: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is StepOutcome.OK


class Executor(Protocol):
    """Tool çalıştırma arayüzü."""

    def execute(self, tool: ToolSpec, arguments: Mapping[str, Any]) -> ExecutionResult: ...


class ReadOnlyHTTPExecutor:
    """Salt-okunur HTTP sağlayıcıları için executor.

    Yazma işlemlerini kabul etmez: ``ToolSpec`` doğrulayıcısı zaten canlı
    ortamda yazmayı yasaklar, burası ikinci savunma hattıdır.
    """

    def __init__(
        self,
        adapter: ProviderAdapter,
        client: httpx.Client,
        *,
        base_url: str | None = None,
        cassette: CassetteTransport | None = None,
    ) -> None:
        if adapter.base_url is None and base_url is None:
            raise ValueError(f"{adapter.name}: HTTP executor için base_url gerekli")
        self.adapter = adapter
        self.client = client
        self.base_url = base_url or adapter.base_url or ""
        #: İstemcinin taşıma katmanına açıkça verilir. Executor cassette'i
        #: kullanmaz, yalnızca hangi kaydın tüketildiğini raporlar; bu yüzden
        #: istemcinin özel alanlarına uzanmak yerine parametre olarak alınır.
        self.cassette = cassette

    def execute(self, tool: ToolSpec, arguments: Mapping[str, Any]) -> ExecutionResult:
        binding = self.adapter.binding(tool.tool_id)
        if binding is None:
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=dict(arguments),
                outcome=StepOutcome.PLAN_ERROR,
                error=f"{self.adapter.name} sağlayıcısında tanımsız tool: {tool.tool_id}",
            )

        normalized = normalize_arguments(tool, arguments)
        errors = validate_arguments(tool, normalized)
        if errors:
            # Şema hatası bir plan hatasıdır: gürültülü patlar, veriye dönüşmez.
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.PLAN_ERROR,
                error=str(ArgumentError(tool.tool_id, errors)),
            )

        request = binding.build_request(normalized, self.base_url)
        # Adapter'lar bağımsız `httpx.Request` üretir; `Client.send()` bu
        # isteklere client-level başlıkları otomatik birleştirmez. Sağlayıcı
        # kimliği gibi zorunlu varsayılanları burada açıkça uygula.
        for name, value in self.client.headers.items():
            if name not in request.headers:
                request.headers[name] = value
        cassette_key: str | None = None
        if self.cassette is not None:
            cassette_key = self.cassette.key_for(request)
            if tool.tool_id in self.adapter.sequenced_tools:
                self.cassette.mark_sequenced(cassette_key)
            if binding.cassette_sanitizer is not None:
                self.cassette.set_response_sanitizer(
                    cassette_key,
                    binding.cassette_sanitizer,
                )

        started = time.perf_counter()
        try:
            response = self.client.send(request)
        except CassetteMissError as exc:
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.TRANSPORT_ERROR,
                error=str(exc),
                cassette_key=cassette_key,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except httpx.HTTPError as exc:
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.TRANSPORT_ERROR,
                error=f"{type(exc).__name__}: {exc}",
                cassette_key=cassette_key,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        raw = response.content
        raw_hash = sha256_hex(raw) if raw else None
        try:
            payload = response.json() if raw else None
        except ValueError as exc:
            # Ayrıştırılamayan gövdenin anlamı HTTP durumuna bağlıdır ve bu
            # ayrım kritiktir:
            #
            #   2xx + bozuk gövde -> gerçekten kırık, altyapı hatası, veri olmaz
            #   4xx/5xx + bozuk gövde -> domain hatası, ground-truth olabilir
            #
            # İzmir CKAN'ı bunun canlı örneğidir: var olmayan bir veri seti
            # istendiğinde CKAN'ın standart JSON hata zarfı yerine portalın
            # kendi HTML 404 sayfasını döndürür. Bunu altyapı hatası saymak
            # "beklenen hata" senaryolarını tamamen imkânsız kılardı.
            if response.is_success:
                return ExecutionResult(
                    tool_id=tool.tool_id,
                    execution_class=tool.execution_class,
                    arguments=normalized,
                    outcome=StepOutcome.TRANSPORT_ERROR,
                    error=f"başarılı yanıt JSON olarak ayrıştırılamadı: {exc}",
                    status_code=response.status_code,
                    cassette_key=cassette_key,
                    raw_response_hash=raw_hash,
                    latency_ms=latency_ms,
                )
            content_type = response.headers.get("content-type", "bilinmiyor").split(";")[0]
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.UNEXPECTED_ERROR,
                status_code=response.status_code,
                response=None,
                error=f"HTTP {response.status_code} ({content_type} gövde, JSON değil)",
                cassette_key=cassette_key,
                raw_response_hash=raw_hash,
                latency_ms=latency_ms,
            )

        try:
            normalized_response = binding.normalize(payload)
        except ToolExecutionError as exc:
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.TRANSPORT_ERROR,
                error=str(exc),
                status_code=response.status_code,
                cassette_key=cassette_key,
                latency_ms=latency_ms,
            )

        # HTTP 200 olmayan her şey burada "hata"dır; planın bunu bekleyip
        # beklemediğine runner karar verir.
        outcome = StepOutcome.OK if response.is_success else StepOutcome.UNEXPECTED_ERROR
        return ExecutionResult(
            tool_id=tool.tool_id,
            execution_class=tool.execution_class,
            arguments=normalized,
            outcome=outcome,
            status_code=response.status_code,
            response=normalized_response,
            error=None if response.is_success else f"HTTP {response.status_code}",
            cassette_key=cassette_key,
            raw_response_hash=raw_hash,
            latency_ms=latency_ms,
        )
