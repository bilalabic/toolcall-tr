"""GBIF lisans ve provenance sınırı."""

from __future__ import annotations

from toolcall_tr.pipeline.environment import build_default_registry
from toolcall_tr.providers.gbif.biodiversity import (
    GET_SPECIES,
    MATCH_SPECIES_NAME,
    SEARCH_OCCURRENCES,
    adapter,
    normalize_occurrences,
)


def test_occurrence_istegi_iki_izinli_lisansi_tekrarlar() -> None:
    binding = adapter.binding(SEARCH_OCCURRENCES.tool_id)
    assert binding is not None
    request = binding.build_request(
        {"taxon_key": 2878688, "country_code": "TR", "limit": 5},
        adapter.base_url or "",
    )
    assert request.url.params.get_list("license") == ["CC0_1_0", "CC_BY_4_0"]
    assert request.url.params["taxonKey"] == "2878688"
    assert request.url.params["country"] == "TR"
    assert request.url.params["hasCoordinate"] == "true"


def test_normalizer_yalnizca_cc0_ve_cc_by_kayitlarini_tutar() -> None:
    def row(key: int, license_value: str) -> dict[str, object]:
        return {
            "key": key,
            "datasetKey": f"dataset-{key}",
            "publishingOrgKey": f"org-{key}",
            "license": license_value,
            "scientificName": "Quercus robur",
            "countryCode": "TR",
        }

    result = normalize_occurrences(
        {
            "results": [
                row(3, "http://creativecommons.org/licenses/by-nc/4.0/legalcode"),
                row(2, "https://creativecommons.org/licenses/by/4.0/legalcode"),
                row(1, "CC0_1_0"),
                {"key": 4, "license": "CC_BY_4_0"},
            ]
        }
    )
    assert [item["occurrence_id"] for item in result["results"]] == [1, 2]
    assert [item["license"] for item in result["results"]] == ["CC0-1.0", "CC-BY-4.0"]
    assert result["filtered_out_count"] == 2


def test_default_registry_gbif_araclarini_icerir() -> None:
    registry = build_default_registry()
    assert registry.require(MATCH_SPECIES_NAME.tool_id) == MATCH_SPECIES_NAME
    assert registry.require(GET_SPECIES.tool_id) == GET_SPECIES
    assert registry.require(SEARCH_OCCURRENCES.tool_id) == SEARCH_OCCURRENCES
