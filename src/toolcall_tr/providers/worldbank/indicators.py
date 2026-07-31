"""World Bank Indicators API v2; yalnızca WDI source=2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://api.worldbank.org"
PROVIDER = "worldbank_wdi"
NAMESPACE = "worldbank_wdi"
LICENSE = "CC-BY-4.0-WORLD-BANK-TERMS"
ATTRIBUTION = "World Bank, World Development Indicators"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="indicators-api-v2/2026-07",
    operation_id="country_indicator",
    upstream_url=f"{BASE_URL}/v2",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    countries = ";".join(str(code).upper() for code in arguments["country_codes"])
    indicator = arguments["indicator_code"]
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/v2/country/{countries}/indicator/{indicator}",
        params={
            "format": "json",
            "source": 2,
            "date": f"{arguments['start_year']}:{arguments['end_year']}",
            "per_page": 1000,
        },
    )


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
        raise ToolExecutionError("World Bank yanıt zarfı geçersiz")
    results = [
        {
            "country_code": str(row["countryiso3code"]),
            "country_name": str(row["country"]["value"]),
            "indicator_code": str(row["indicator"]["id"]),
            "indicator_name": str(row["indicator"]["value"]),
            "year": int(row["date"]),
            "value": row.get("value"),
        }
        for row in payload[1]
        if isinstance(row, dict)
    ]
    results.sort(key=lambda row: (row["country_code"], row["year"]))
    return {"count": len(results), "results": results}


GET_INDICATOR_TIME_SERIES = ToolSpec(
    tool_id="statistics.get_indicator_time_series",
    provider=PROVIDER,
    name="get_indicator_time_series",
    description_tr="WDI source=2 üzerinden ülkelerin belirli gösterge zaman serisini getirir.",
    parameters=(
        ParamSpec(name="country_codes", type="array", item_type="string", description_tr="ISO3 ülke kodları.", required=True, min_items=1, max_items=5, semantic_type="country_code"),
        ParamSpec(name="indicator_code", type="string", description_tr="Allowlist'teki WDI gösterge kodu.", required=True, semantic_type="indicator_code"),
        ParamSpec(name="start_year", type="integer", description_tr="Başlangıç yılı.", required=True, minimum=1960, maximum=2100),
        ParamSpec(name="end_year", type="integer", description_tr="Bitiş yılı.", required=True, minimum=1960, maximum=2100),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Veri noktası sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].country_code", type="string", description_tr="ISO3 ülke kodu.", semantic_type="country_code"),
        OutputField(path="results[*].indicator_code", type="string", description_tr="Gösterge kodu.", semantic_type="indicator_code"),
        OutputField(path="results[*].year", type="integer", description_tr="Yıl."),
        OutputField(path="results[*].value", type="number", description_tr="Gösterge değeri."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS = (GET_INDICATOR_TIME_SERIES,)
adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(ToolBinding(GET_INDICATOR_TIME_SERIES, _request, normalize),),
)
