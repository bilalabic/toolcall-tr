"""GeoNames Türkiye yerel sağlayıcısı."""

from __future__ import annotations

import json
from pathlib import Path

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import StepOutcome
from toolcall_tr.providers.geonames.geography import (
    FIND_NEARBY_PLACES,
    GET_PLACE,
    LOOKUP_POSTAL_CODE,
    SEARCH_PLACES,
    build_adapter,
)


def _executor(repo_root: Path) -> DerivedLocalExecutor:
    adapter = build_adapter(repo_root / "data" / "snapshots" / "geonames_tr")
    return DerivedLocalExecutor(adapter)


def test_snapshot_81_il_merkezini_icerir(repo_root: Path) -> None:
    manifest = json.loads(
        (repo_root / "data" / "snapshots" / "geonames_tr" / "SNAPSHOT.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["files"]["places.jsonl"]["row_count"] == 81


def test_turkce_ve_ascii_ad_eslesir(repo_root: Path) -> None:
    executor = _executor(repo_root)
    turkish = executor.execute(SEARCH_PLACES, {"query": "Iğdır"})
    ascii_result = executor.execute(SEARCH_PLACES, {"query": "Igdir"})
    assert turkish.outcome is StepOutcome.OK
    assert turkish.response == ascii_result.response
    assert turkish.response["results"][0]["name"] == "Iğdır"


def test_get_place_onceki_arama_kimligini_kullanabilir(repo_root: Path) -> None:
    executor = _executor(repo_root)
    search = executor.execute(SEARCH_PLACES, {"query": "Elazığ"})
    geoname_id = search.response["results"][0]["geoname_id"]
    detail = executor.execute(GET_PLACE, {"geoname_id": geoname_id})
    assert detail.outcome is StepOutcome.OK
    assert detail.response["name"] == "Elazığ"
    assert detail.response["timezone"] == "Europe/Istanbul"


def test_bilinmeyen_geoname_id_beklenen_domain_hatasina_uygun(repo_root: Path) -> None:
    result = _executor(repo_root).execute(GET_PLACE, {"geoname_id": 999999999})
    assert result.outcome is StepOutcome.UNEXPECTED_ERROR
    assert result.status_code == 404
    assert result.error is not None
    assert "bulunamadı" in result.error


def test_yakindaki_il_merkezleri_mesafeye_gore_siralanir(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        FIND_NEARBY_PLACES,
        {
            "latitude": 39.9334,
            "longitude": 32.8597,
            "radius_km": 250,
            "limit": 5,
        },
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["results"][0]["name"] == "Ankara"
    distances = [row["distance_km"] for row in result.response["results"]]
    assert distances == sorted(distances)


def test_posta_kodu_il_ilce_metadata_dondurur(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        LOOKUP_POSTAL_CODE,
        {"postal_code": "23200", "limit": 10},
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["count"] >= 1
    assert all(row["postal_code"] == "23200" for row in result.response["results"])


def test_arama_semasi_enum_boolean_array_cesitliligi_tasir() -> None:
    parameters = {parameter.name: parameter for parameter in SEARCH_PLACES.parameters}
    assert parameters["sort_by"].enum == ["relevance", "population"]
    assert parameters["include_alternate_names"].type == "boolean"
    assert parameters["province_codes"].type == "array"
    assert parameters["province_codes"].item_type == "string"
