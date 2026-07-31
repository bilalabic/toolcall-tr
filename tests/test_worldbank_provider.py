"""World Bank WDI sağlayıcı sınırı."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import StepOutcome
from toolcall_tr.pipeline.environment import build_default_registry
from toolcall_tr.providers.base import ToolExecutionError
from toolcall_tr.providers.worldbank.indicators import (
    GET_INDICATOR_TIME_SERIES,
    adapter,
    normalize,
)
from toolcall_tr.providers.worldbank.search import SEARCH_INDICATOR
from toolcall_tr.providers.worldbank.search import build_adapter as build_search_adapter


def test_wdi_istegi_source_2_ile_sabitlenir() -> None:
    binding = adapter.binding(GET_INDICATOR_TIME_SERIES.tool_id)
    assert binding is not None
    request = binding.build_request(
        {
            "country_codes": ["TUR"],
            "indicator_code": "SP.POP.TOTL",
            "start_year": 2010,
            "end_year": 2024,
        },
        adapter.base_url or "",
    )
    assert request.url.path == "/v2/country/TUR/indicator/SP.POP.TOTL"
    assert request.url.params["source"] == "2"
    assert request.url.params["date"] == "2010:2024"


def test_wdi_yaniti_ulke_ve_yila_gore_siralanir() -> None:
    payload = [
        {"page": 1, "pages": 1, "total": 2},
        [
            {
                "countryiso3code": "TUR",
                "country": {"value": "Türkiye"},
                "indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
                "date": "2024",
                "value": 85_000_000,
            },
            {
                "countryiso3code": "TUR",
                "country": {"value": "Türkiye"},
                "indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
                "date": "2023",
                "value": 84_000_000,
            },
        ],
    ]
    result = normalize(payload)
    assert result["count"] == 2
    assert [row["year"] for row in result["results"]] == [2023, 2024]


def test_wdi_gecersiz_zarf_reddedilir() -> None:
    with pytest.raises(ToolExecutionError, match="zarfı geçersiz"):
        normalize({"results": []})


def test_wdi_allowlist_turkce_ve_ascii_eslesir(repo_root: Path) -> None:
    executor = DerivedLocalExecutor(
        build_search_adapter(repo_root / "data" / "snapshots" / "wdi_indicators")
    )
    turkish = executor.execute(SEARCH_INDICATOR, {"query": "nüfus"})
    ascii_result = executor.execute(SEARCH_INDICATOR, {"query": "nufus"})
    assert turkish.outcome is StepOutcome.OK
    assert turkish.response == ascii_result.response
    assert turkish.response["results"][0]["code"] == "SP.POP.TOTL"


def test_default_registry_wdi_araclarini_icerir() -> None:
    registry = build_default_registry()
    assert registry.require("statistics.search_indicator") == SEARCH_INDICATOR
    assert registry.require("statistics.get_indicator_time_series") == GET_INDICATOR_TIME_SERIES
