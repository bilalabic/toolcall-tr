"""Frankfurter v2 adaptörü; oranlar yalnızca ECB sağlayıcısına pinlenir."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://api.frankfurter.dev"
PROVIDER = "frankfurter_ecb"
NAMESPACE = "frankfurter_ecb"
LICENSE = "ECB-TERMS"
ATTRIBUTION = "European Central Bank euro foreign exchange reference rates via Frankfurter"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="frankfurter-v2/2026-07",
    upstream_url=f"{BASE_URL}/v2",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

_BASE = ParamSpec(
    name="base",
    type="string",
    description_tr="Kaynak para biriminin üç harfli ISO 4217 kodu.",
    required=True,
    semantic_type="currency_code",
    pattern="^[A-Z]{3}$",
)
_QUOTE = ParamSpec(
    name="quote",
    type="string",
    description_tr="Hedef para biriminin üç harfli ISO 4217 kodu.",
    required=True,
    semantic_type="currency_code",
    pattern="^[A-Z]{3}$",
)


def _rate_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params: dict[str, Any] = {
        "base": arguments["base"],
        "quotes": arguments["quote"],
        "providers": "ECB",
    }
    if arguments.get("date") is not None:
        params["from"] = arguments["date"]
        params["to"] = arguments["date"]
    return httpx.Request("GET", f"{base_url.rstrip('/')}/v2/rates", params=params)


def _currencies_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    del arguments
    return httpx.Request("GET", f"{base_url.rstrip('/')}/v2/currencies")


def normalize_rates(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ToolExecutionError(f"kur yanıtı liste değil: {type(payload).__name__}")
    results = [
        {
            "date": str(item["date"]),
            "base": str(item["base"]),
            "quote": str(item["quote"]),
            "rate": float(item["rate"]),
        }
        for item in payload
        if isinstance(item, dict)
    ]
    results.sort(key=lambda item: (item["date"], item["base"], item["quote"]))
    return {"count": len(results), "results": results}


def normalize_currencies(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ToolExecutionError("para birimi yanıtı liste değil")
    results = [
        {"code": str(item["iso_code"]), "name": str(item["name"])}
        for item in payload
        if isinstance(item, dict) and item.get("iso_code") and item.get("name")
    ]
    results.sort(key=lambda item: item["code"])
    return {"count": len(results), "results": results}


_RATE_OUTPUTS = (
    OutputField(
        path="count",
        type="integer",
        description_tr="Dönen kur kaydı sayısı.",
        semantic_type="result_count",
    ),
    OutputField(path="results[*].date", type="string", description_tr="Kur tarihi."),
    OutputField(
        path="results[*].base",
        type="string",
        description_tr="Kaynak para birimi.",
        semantic_type="currency_code",
    ),
    OutputField(
        path="results[*].quote",
        type="string",
        description_tr="Hedef para birimi.",
        semantic_type="currency_code",
    ),
    OutputField(path="results[*].rate", type="number", description_tr="Referans kur."),
)

GET_EXCHANGE_RATE = ToolSpec(
    tool_id="currency.get_exchange_rate",
    provider=PROVIDER,
    name="get_exchange_rate",
    description_tr="ECB kaynaklı en güncel referans döviz kurunu getirir.",
    parameters=(_BASE, _QUOTE),
    outputs=_RATE_OUTPUTS,
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

GET_HISTORICAL_EXCHANGE_RATE = ToolSpec(
    tool_id="currency.get_historical_exchange_rate",
    provider=PROVIDER,
    name="get_historical_exchange_rate",
    description_tr="ECB kaynaklı belirli bir tarihin referans döviz kurunu getirir.",
    parameters=(
        _BASE,
        _QUOTE,
        ParamSpec(
            name="date",
            type="string",
            description_tr="ISO 8601 biçiminde tarih (YYYY-MM-DD).",
            required=True,
            semantic_type="date",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ),
    outputs=_RATE_OUTPUTS,
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

LIST_SUPPORTED_CURRENCIES = ToolSpec(
    tool_id="currency.list_supported_currencies",
    provider=PROVIDER,
    name="list_supported_currencies",
    description_tr="Frankfurter tarafından tanınan para birimi kodlarını listeler.",
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Para birimi sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].code",
            type="string",
            description_tr="ISO 4217 kodu.",
            semantic_type="currency_code",
        ),
        OutputField(path="results[*].name", type="string", description_tr="Para birimi adı."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (
    GET_EXCHANGE_RATE,
    GET_HISTORICAL_EXCHANGE_RATE,
    LIST_SUPPORTED_CURRENCIES,
)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(GET_EXCHANGE_RATE, _rate_request, normalize_rates),
        ToolBinding(GET_HISTORICAL_EXCHANGE_RATE, _rate_request, normalize_rates),
        ToolBinding(LIST_SUPPORTED_CURRENCIES, _currencies_request, normalize_currencies),
    ),
)
