"""GBIF API v1; occurrence sonuçları CC0 ve CC BY ile sınırlandırılır."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://api.gbif.org"
PROVIDER = "gbif"
NAMESPACE = "gbif"
LICENSE = "GBIF-FILTERED-CC0-CC-BY-4.0"
ATTRIBUTION = "GBIF.org ve occurrence kayıtlarını yayımlayan veri sağlayıcıları"

_ALLOWED_LICENSES = {
    "CC0_1_0": "CC0-1.0",
    "CC_BY_4_0": "CC-BY-4.0",
    "http://creativecommons.org/publicdomain/zero/1.0/legalcode": "CC0-1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/legalcode": "CC0-1.0",
    "http://creativecommons.org/licenses/by/4.0/legalcode": "CC-BY-4.0",
    "https://creativecommons.org/licenses/by/4.0/legalcode": "CC-BY-4.0",
}

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="gbif-api-v1/2026-07",
    upstream_url=f"{BASE_URL}/v1",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _match_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/v1/species/match",
        params={"name": arguments["scientific_name"], "verbose": "false"},
    )


def normalize_match(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ToolExecutionError("GBIF species match yanıtı geçersiz")
    usage_key = payload.get("usageKey") or payload.get("key")
    matched = usage_key is not None and payload.get("matchType") != "NONE"
    return {
        "matched": matched,
        "usage_key": int(usage_key) if usage_key is not None and matched else None,
        "scientific_name": str(payload.get("scientificName") or ""),
        "canonical_name": str(payload.get("canonicalName") or ""),
        "rank": str(payload.get("rank") or ""),
        "status": str(payload.get("status") or ""),
        "confidence": int(payload.get("confidence") or 0),
        "match_type": str(payload.get("matchType") or "NONE"),
    }


def _species_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/v1/species/{int(arguments['taxon_key'])}",
    )


def normalize_species(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("key") is None:
        raise ToolExecutionError("GBIF species ayrıntı yanıtı geçersiz")
    return {
        "taxon_key": int(payload["key"]),
        "scientific_name": str(payload.get("scientificName") or ""),
        "canonical_name": str(payload.get("canonicalName") or ""),
        "rank": str(payload.get("rank") or ""),
        "status": str(payload.get("taxonomicStatus") or ""),
        "kingdom": str(payload.get("kingdom") or ""),
        "phylum": str(payload.get("phylum") or ""),
        "class": str(payload.get("class") or ""),
        "order": str(payload.get("order") or ""),
        "family": str(payload.get("family") or ""),
        "genus": str(payload.get("genus") or ""),
    }


def _occurrence_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params: list[tuple[str, Any]] = [
        ("taxonKey", int(arguments["taxon_key"])),
        ("country", str(arguments["country_code"]).upper()),
        ("license", "CC0_1_0"),
        ("license", "CC_BY_4_0"),
        ("hasCoordinate", "true"),
        ("limit", int(arguments.get("limit", 10))),
        ("offset", 0),
    ]
    if arguments.get("year") is not None:
        params.append(("year", int(arguments["year"])))
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/v1/occurrence/search",
        params=params,
    )


def _normalized_license(value: object) -> str | None:
    return _ALLOWED_LICENSES.get(str(value).rstrip("/"))


def normalize_occurrences(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ToolExecutionError("GBIF occurrence search yanıtı geçersiz")

    results: list[dict[str, Any]] = []
    filtered_out_count = 0
    for row in payload["results"]:
        if not isinstance(row, dict):
            filtered_out_count += 1
            continue
        license_id = _normalized_license(row.get("license"))
        if license_id is None:
            filtered_out_count += 1
            continue
        required = ("key", "datasetKey", "publishingOrgKey")
        if any(row.get(field) is None for field in required):
            filtered_out_count += 1
            continue
        results.append(
            {
                "occurrence_id": int(row["key"]),
                "dataset_key": str(row["datasetKey"]),
                "publishing_org_key": str(row["publishingOrgKey"]),
                "license": license_id,
                "scientific_name": str(row.get("scientificName") or ""),
                "event_date": str(row.get("eventDate") or ""),
                "country_code": str(row.get("countryCode") or ""),
                "latitude": row.get("decimalLatitude"),
                "longitude": row.get("decimalLongitude"),
                "basis_of_record": str(row.get("basisOfRecord") or ""),
                "publisher": str(row.get("publishingOrgName") or ""),
            }
        )
    results.sort(key=lambda row: row["occurrence_id"])
    return {
        "count": len(results),
        "filtered_out_count": filtered_out_count,
        "results": results,
    }


MATCH_SPECIES_NAME = ToolSpec(
    tool_id="biodiversity.match_species_name",
    provider=PROVIDER,
    name="match_species_name",
    description_tr="Bilimsel adı GBIF taksonomi omurgasındaki tek bir taksonla eşleştirir.",
    parameters=(
        ParamSpec(
            name="scientific_name",
            type="string",
            description_tr="Eşleştirilecek bilimsel tür adı.",
            required=True,
            min_length=3,
            semantic_type="scientific_name",
        ),
    ),
    outputs=(
        OutputField(path="matched", type="boolean", description_tr="Bir takson eşleşip eşleşmediği."),
        OutputField(path="usage_key", type="integer", description_tr="GBIF takson anahtarı.", semantic_type="taxon_key"),
        OutputField(path="scientific_name", type="string", description_tr="Eşleşen bilimsel ad.", semantic_type="scientific_name"),
        OutputField(path="rank", type="string", description_tr="Taksonomik sıra."),
        OutputField(path="confidence", type="integer", description_tr="Eşleşme güven puanı."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_SPECIES = ToolSpec(
    tool_id="biodiversity.get_species",
    provider=PROVIDER,
    name="get_species",
    description_tr="GBIF takson anahtarının sınıflandırma ayrıntılarını getirir.",
    parameters=(
        ParamSpec(
            name="taxon_key",
            type="integer",
            description_tr="GBIF takson anahtarı.",
            required=True,
            minimum=1,
            semantic_type="taxon_key",
        ),
    ),
    outputs=(
        OutputField(path="taxon_key", type="integer", description_tr="GBIF takson anahtarı.", semantic_type="taxon_key"),
        OutputField(path="scientific_name", type="string", description_tr="Bilimsel ad.", semantic_type="scientific_name"),
        OutputField(path="rank", type="string", description_tr="Taksonomik sıra."),
        OutputField(path="family", type="string", description_tr="Familya."),
        OutputField(path="genus", type="string", description_tr="Cins."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

SEARCH_OCCURRENCES = ToolSpec(
    tool_id="biodiversity.search_occurrences",
    provider=PROVIDER,
    name="search_occurrences",
    description_tr="Bir taksonun koordinatlı GBIF kayıtlarını yalnızca CC0 veya CC BY lisansıyla arar.",
    parameters=(
        ParamSpec(
            name="taxon_key",
            type="integer",
            description_tr="GBIF takson anahtarı.",
            required=True,
            minimum=1,
            semantic_type="taxon_key",
        ),
        ParamSpec(
            name="country_code",
            type="string",
            description_tr="ISO 3166-1 alpha-2 ülke kodu.",
            required=True,
            pattern=r"^[A-Z]{2}$",
            semantic_type="country_code",
        ),
        ParamSpec(
            name="year",
            type="integer",
            description_tr="İsteğe bağlı kayıt yılı.",
            minimum=1600,
            maximum=2100,
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="En fazla kayıt sayısı.",
            minimum=1,
            maximum=50,
            has_default=True,
            default=10,
        ),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="İzinli kayıt sayısı.", semantic_type="result_count"),
        OutputField(path="filtered_out_count", type="integer", description_tr="Lisans veya provenance nedeniyle çıkarılan kayıt sayısı."),
        OutputField(path="results[*].occurrence_id", type="integer", description_tr="GBIF occurrence anahtarı.", semantic_type="occurrence_id"),
        OutputField(path="results[*].dataset_key", type="string", description_tr="Kaynak veri kümesi anahtarı.", semantic_type="dataset_key"),
        OutputField(path="results[*].publishing_org_key", type="string", description_tr="Yayımlayan kuruluş anahtarı."),
        OutputField(path="results[*].license", type="string", description_tr="Normalize edilmiş kayıt lisansı."),
        OutputField(path="results[*].scientific_name", type="string", description_tr="Bilimsel ad.", semantic_type="scientific_name"),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (MATCH_SPECIES_NAME, GET_SPECIES, SEARCH_OCCURRENCES)
adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(MATCH_SPECIES_NAME, _match_request, normalize_match),
        ToolBinding(GET_SPECIES, _species_request, normalize_species),
        ToolBinding(SEARCH_OCCURRENCES, _occurrence_request, normalize_occurrences),
    ),
)
