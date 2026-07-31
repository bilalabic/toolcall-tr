"""Güvenli hesaplama ve dondurulmuş saat sağlayıcısı."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import (
    LocalProviderAdapter,
    LocalToolBinding,
    ToolExecutionError,
)

PROVIDER = "general_local"
VERSION = "general_local/1.0.0"
LICENSE = "Apache-2.0"
ATTRIBUTION = "ToolCall-TR katkıcıları; deterministik yerel uygulama"

TIMEZONES = (
    "UTC",
    "Europe/Istanbul",
    "Europe/London",
    "America/New_York",
    "Asia/Tokyo",
)

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version=VERSION,
    upstream_url="https://general-local.toolcall-tr.test",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

CALCULATOR_EVALUATE = ToolSpec(
    tool_id="calculator.evaluate",
    provider=PROVIDER,
    name="evaluate",
    description_tr=(
        "Yalnızca sayılar, parantezler ve temel aritmetik işleçlerden oluşan "
        "bir ifadeyi güvenli ve deterministik biçimde hesaplar."
    ),
    parameters=(
        ParamSpec(
            name="expression",
            type="string",
            description_tr="Hesaplanacak aritmetik ifade.",
            required=True,
            min_length=1,
            max_length=160,
        ),
        ParamSpec(
            name="precision",
            type="integer",
            description_tr="Sonucun yuvarlanacağı ondalık basamak sayısı.",
            enum=[0, 2, 4, 6],
            has_default=True,
            default=4,
        ),
    ),
    outputs=(
        OutputField(
            path="expression",
            type="string",
            description_tr="Hesaplanan ifade.",
        ),
        OutputField(
            path="result",
            type="number",
            description_tr="Sonlu sayısal sonuç.",
            semantic_type="calculation_result",
        ),
        OutputField(
            path="precision",
            type="integer",
            description_tr="Uygulanan ondalık basamak sayısı.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    source=_SOURCE,
)

TIME_GET_LOCAL_TIME = ToolSpec(
    tool_id="time.get_local_time",
    provider=PROVIDER,
    name="get_local_time",
    description_tr=(
        "Ortamın dondurulmuş UTC saatini seçilen IANA saat dilimine dönüştürür; "
        "gerçek sistem saatini okumaz."
    ),
    parameters=(
        ParamSpec(
            name="timezone",
            type="string",
            description_tr="Dönüşüm yapılacak desteklenen IANA saat dilimi.",
            required=True,
            enum=list(TIMEZONES),
            semantic_type="timezone",
        ),
        ParamSpec(
            name="include_utc_offset",
            type="boolean",
            description_tr="UTC farkının yanıta eklenip eklenmeyeceği.",
            has_default=True,
            default=True,
        ),
    ),
    outputs=(
        OutputField(
            path="timezone",
            type="string",
            description_tr="Seçilen IANA saat dilimi.",
            semantic_type="timezone",
        ),
        OutputField(
            path="local_time",
            type="string",
            description_tr="Saat dilimine dönüştürülmüş ISO 8601 tarih ve saat.",
            semantic_type="datetime",
        ),
        OutputField(
            path="utc_offset",
            type="string",
            description_tr="İstenmişse +03:00 biçimindeki UTC farkı.",
        ),
        OutputField(
            path="is_dst",
            type="boolean",
            description_tr="Yaz saati uygulamasının etkin olup olmadığı.",
        ),
        OutputField(
            path="frozen_utc_time",
            type="string",
            description_tr="Dönüşümün dayandığı dondurulmuş UTC tarih ve saati.",
            semantic_type="datetime",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (CALCULATOR_EVALUATE, TIME_GET_LOCAL_TIME)

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_MAX_ABS_VALUE = 1_000_000_000_000_000.0
_MAX_AST_NODES = 80
_MAX_EXPONENT = 12


def build_adapter(now: datetime) -> LocalProviderAdapter:
    """Ortamın dondurulmuş saatine bağlı yerel adaptörü kurar."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("general_local için saat timezone-aware olmalıdır")
    frozen_now = now.astimezone(UTC)
    return LocalProviderAdapter(
        name=PROVIDER,
        bindings=(
            LocalToolBinding(spec=CALCULATOR_EVALUATE, run=_run_calculator),
            LocalToolBinding(
                spec=TIME_GET_LOCAL_TIME,
                run=lambda arguments: _run_local_time(arguments, frozen_now),
            ),
        ),
        license=LICENSE,
        attribution=ATTRIBUTION,
    )


def _run_calculator(arguments: Mapping[str, Any]) -> dict[str, Any]:
    expression = str(arguments["expression"]).strip()
    try:
        parsed = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ToolExecutionError("Geçersiz aritmetik ifade", status_code=422) from exc
    if sum(1 for _ in ast.walk(parsed)) > _MAX_AST_NODES:
        raise ToolExecutionError("Aritmetik ifade fazla karmaşık", status_code=422)

    try:
        result = _evaluate_node(parsed.body)
    except ZeroDivisionError as exc:
        raise ToolExecutionError("Sıfıra bölme tanımsızdır", status_code=422) from exc
    except (OverflowError, ValueError) as exc:
        raise ToolExecutionError(str(exc), status_code=422) from exc

    precision = int(arguments["precision"])
    return {
        "expression": expression,
        "result": round(result, precision),
        "precision": precision,
    }


def _evaluate_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("İfadede yalnızca sonlu sayılar kullanılabilir")
        return _bounded(float(value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        value = _evaluate_node(node.operand)
        return _bounded(value if isinstance(node.op, ast.UAdd) else -value)
    if isinstance(node, ast.BinOp):
        function = _BINARY_OPERATORS.get(type(node.op))
        if function is None:
            raise ValueError("Desteklenmeyen aritmetik işleç")
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError("Üs değeri izin verilen sınırı aşıyor")
        return _bounded(function(left, right))
    raise ValueError("İfadede değişken, fonksiyon veya desteklenmeyen sözdizimi var")


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("Sonuç sonlu bir sayı olmalıdır")
    if abs(value) > _MAX_ABS_VALUE:
        raise ValueError("Sonuç izin verilen sayısal sınırı aşıyor")
    return value


def _run_local_time(arguments: Mapping[str, Any], frozen_now: datetime) -> dict[str, Any]:
    timezone_name = str(arguments["timezone"])
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ToolExecutionError(
            f"Desteklenen saat dilimi yüklenemedi: {timezone_name}",
            status_code=422,
        ) from exc
    local = frozen_now.astimezone(timezone)
    response: dict[str, Any] = {
        "timezone": timezone_name,
        "local_time": local.isoformat(timespec="seconds"),
        "is_dst": bool(local.dst()),
        "frozen_utc_time": frozen_now.isoformat(timespec="seconds"),
    }
    if bool(arguments["include_utc_offset"]):
        raw_offset = local.strftime("%z")
        response["utc_offset"] = f"{raw_offset[:3]}:{raw_offset[3:]}"
    return response

