"""Allowlist tabanlı güvenli web metadata federasyonu."""

from __future__ import annotations

from pathlib import Path

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import StepOutcome
from toolcall_tr.providers.federated_web.metadata import (
    GET_RESULT_METADATA,
    SEARCH,
    build_adapter,
)


def _executor(repo_root: Path) -> DerivedLocalExecutor:
    return DerivedLocalExecutor(
        build_adapter(
            geonames_dir=repo_root / "data" / "snapshots" / "geonames_tr",
            wdi_dir=repo_root / "data" / "snapshots" / "wdi_indicators",
            holidays_dir=repo_root / "data" / "snapshots" / "tr_public_holidays",
        )
    )


def test_web_search_yalniz_metadata_dondurur(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        SEARCH,
        {"query": "Ankara", "result_type": "all", "limit": 5},
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["count"] >= 1
    row = result.response["results"][0]
    assert row["title"] == "Ankara"
    assert row["source"] == "geonames"
    assert set(row) == {
        "license",
        "result_id",
        "result_type",
        "source",
        "title",
        "updated_at",
        "url",
    }


def test_web_search_turkce_ascii_eslesir(repo_root: Path) -> None:
    executor = _executor(repo_root)
    turkish = executor.execute(SEARCH, {"query": "Iğdır"})
    ascii_result = executor.execute(SEARCH, {"query": "Igdir"})
    assert turkish.response == ascii_result.response


def test_search_then_get_metadata_zinciri(repo_root: Path) -> None:
    executor = _executor(repo_root)
    search = executor.execute(
        SEARCH,
        {
            "query": "Toplam nüfus",
            "sources": ["world_bank"],
            "result_type": "statistical_indicator",
        },
    )
    result_id = search.response["results"][0]["result_id"]
    detail = executor.execute(GET_RESULT_METADATA, {"result_id": result_id})
    assert detail.outcome is StepOutcome.OK
    assert detail.response["metadata"]["indicator_code"] == "SP.POP.TOTL"


def test_tatil_metadata_arama(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        SEARCH,
        {
            "query": "Kurban Bayramı",
            "sources": ["official_calendar"],
            "result_type": "public_holiday",
            "limit": 10,
        },
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["count"] == 5


def test_bilinmeyen_kaynak_tur_hatasi(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        SEARCH,
        {"query": "Ankara", "sources": ["open_internet"]},
    )
    assert result.outcome is StepOutcome.UNEXPECTED_ERROR
    assert result.status_code == 422


def test_schema_array_enum_ve_icerik_siniri_tasir() -> None:
    parameters = {parameter.name: parameter for parameter in SEARCH.parameters}
    assert parameters["sources"].type == "array"
    assert parameters["result_type"].enum == [
        "all",
        "place",
        "statistical_indicator",
        "public_holiday",
    ]
    assert "snippet" not in {output.path for output in SEARCH.outputs}
    assert "content" not in {output.path for output in SEARCH.outputs}
