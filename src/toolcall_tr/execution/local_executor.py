"""Yerel hesaplama executor'ı — ağa çıkmayan tool'lar için.

HTTP executor ile aynı `Executor` arayüzünü uygular, böylece runner iki türü
ayırt etmek zorunda kalmaz. Tek fark `execution_class` ve cassette anahtarının
daima ``None`` olmasıdır -- ``ExecutedCall`` doğrulayıcısı bunu zorlar.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from toolcall_tr.execution.executor import ExecutionResult
from toolcall_tr.models import StepOutcome, ToolSpec
from toolcall_tr.providers.base import LocalProviderAdapter, ToolExecutionError
from toolcall_tr.schema import ArgumentError, normalize_arguments, validate_arguments

__all__ = ["DerivedLocalExecutor"]


class DerivedLocalExecutor:
    """Dondurulmuş veri üzerinde deterministik hesaplama yapan executor."""

    def __init__(self, adapter: LocalProviderAdapter) -> None:
        self.adapter = adapter

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
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.PLAN_ERROR,
                error=str(ArgumentError(tool.tool_id, errors)),
            )

        started = time.perf_counter()
        try:
            response = binding.run(normalized)
        except ToolExecutionError as exc:
            # Domain hatası: tool bilinçli olarak reddetti. Ground-truth olabilir.
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.UNEXPECTED_ERROR,
                status_code=exc.status_code,
                error=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            # Beklenmeyen istisna implementasyon hatasıdır: gürültülü patlar ve
            # asla veriye dönüşmez.
            return ExecutionResult(
                tool_id=tool.tool_id,
                execution_class=tool.execution_class,
                arguments=normalized,
                outcome=StepOutcome.TRANSPORT_ERROR,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        return ExecutionResult(
            tool_id=tool.tool_id,
            execution_class=tool.execution_class,
            arguments=normalized,
            outcome=StepOutcome.OK,
            # Yerel hesaplamanın HTTP durumu yoktur; 200 uydurmak yanıltıcı olurdu.
            status_code=None,
            response=response,
            cassette_key=None,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
