"""Tam metin/snippet indirmeyen, allowlist kaynaklı web metadata araması."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import (
    LocalProviderAdapter,
    LocalToolBinding,
    ToolExecutionError,
)
from toolcall_tr.turkish.text import ascii_fold_tr, casefold_tr

__all__ = [
    "GET_RESULT_METADATA",
    "PROVIDER",
    "SEARCH",
    "TOOLS",
    "build_adapter",
]

PROVIDER = "federated_web_metadata"
LICENSE = "SOURCE-SPECIFIC-METADATA-ONLY"
ATTRIBUTION = (
    "GeoNames CC BY 4.0, World Bank WDI metadata ve Türkiye resmî tatil "
    "metadata'sından türetilmiş allowlist federasyonu"
)

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="federated_web_metadata/2026-07-v1",
    upstream_url=None,
    license=LICENSE,
    attribution=ATTRIBUTION,
)

SEARCH = ToolSpec(
    tool_id="web.search",
    provider=PROVIDER,
    name="search",
    description_tr=(
        "Allowlist içindeki lisanslı kaynaklarda yalnızca başlık, URL, kaynak, "
        "tür, tarih ve lisans metadata'sı arar; snippet veya sayfa içeriği döndürmez."
    ),
    parameters=(
        ParamSpec(
            name="query",
            type="string",
            description_tr="Tek amaçlı web metadata arama sorgusu.",
            required=True,
            semantic_type="search_query",
            min_length=2,
            max_length=160,
        ),
        ParamSpec(
            name="sources",
            type="array",
            item_type="string",
            description_tr=(
                "İsteğe bağlı kaynak filtresi: geonames, world_bank veya "
                "official_calendar."
            ),
            min_items=1,
            max_items=3,
        ),
        ParamSpec(
            name="result_type",
            type="string",
            description_tr="İsteğe bağlı metadata türü.",
            enum=["all", "place", "statistical_indicator", "public_holiday"],
            has_default=True,
            default="all",
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Döndürülecek en fazla sonuç.",
            minimum=1,
            maximum=20,
            has_default=True,
            default=5,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Dönen metadata sonucu sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].result_id",
            type="string",
            description_tr="Federasyon içi kararlı sonuç kimliği.",
            semantic_type="web_result_id",
        ),
        OutputField(
            path="results[*].title",
            type="string",
            description_tr="Kaynak başlığı.",
        ),
        OutputField(
            path="results[*].url",
            type="string",
            description_tr="Kaynağın kalıcı URL'si.",
        ),
        OutputField(
            path="results[*].source",
            type="string",
            description_tr="Kaynak sağlayıcı.",
        ),
        OutputField(
            path="results[*].result_type",
            type="string",
            description_tr="Metadata türü.",
        ),
        OutputField(
            path="results[*].license",
            type="string",
            description_tr="Kaynağın lisans etiketi.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_RESULT_METADATA = ToolSpec(
    tool_id="web.get_result_metadata",
    provider=PROVIDER,
    name="get_result_metadata",
    description_tr=(
        "Önceki güvenli arama sonucunun metadata ayrıntılarını içerik indirmeden getirir."
    ),
    parameters=(
        ParamSpec(
            name="result_id",
            type="string",
            description_tr="web.search sonucundaki kararlı kimlik.",
            required=True,
            semantic_type="web_result_id",
            pattern=r"^wm_[0-9a-f]{16}$",
            min_length=19,
            max_length=19,
        ),
    ),
    outputs=(
        OutputField(
            path="result_id",
            type="string",
            description_tr="Federasyon içi sonuç kimliği.",
            semantic_type="web_result_id",
        ),
        OutputField(path="title", type="string", description_tr="Kaynak başlığı."),
        OutputField(path="url", type="string", description_tr="Kalıcı URL."),
        OutputField(path="source", type="string", description_tr="Kaynak sağlayıcı."),
        OutputField(path="license", type="string", description_tr="Lisans etiketi."),
        OutputField(path="metadata", type="object", description_tr="İzinli ek metadata."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH, GET_RESULT_METADATA)


def _key(value: str) -> str:
    return ascii_fold_tr(casefold_tr(value)).casefold()


def _result_id(source: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{source}:{source_id}".encode()).hexdigest()[:16]
    return f"wm_{digest}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_adapter(
    *,
    geonames_dir: Path,
    wdi_dir: Path,
    holidays_dir: Path,
) -> LocalProviderAdapter:
    records: list[dict[str, Any]] = []
    snapshot_hashes: dict[str, str] = {}

    geonames_manifest = json.loads(
        (geonames_dir / "SNAPSHOT.json").read_text(encoding="utf-8")
    )
    snapshot_hashes["federated_geonames_tr"] = geonames_manifest["files"][
        "places.jsonl"
    ]["content_hash"]
    for row in _read_jsonl(geonames_dir / "places.jsonl"):
        source_id = str(row["geoname_id"])
        records.append(
            {
                "license": "CC-BY-4.0",
                "metadata": {
                    "country_code": row["country_code"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "population": row["population"],
                    "timezone": row["timezone"],
                },
                "result_id": _result_id("geonames", source_id),
                "result_type": "place",
                "source": "geonames",
                "source_id": source_id,
                "title": str(row["name"]),
                "updated_at": geonames_manifest["retrieved_at"],
                "url": f"https://www.geonames.org/{source_id}/",
            }
        )

    wdi_manifest = json.loads((wdi_dir / "SNAPSHOT.json").read_text(encoding="utf-8"))
    snapshot_hashes["federated_wdi_indicators"] = wdi_manifest["content_hash"]
    for row in _read_jsonl(wdi_dir / "indicators.jsonl"):
        source_id = str(row["code"])
        records.append(
            {
                "license": wdi_manifest["license"],
                "metadata": {
                    "indicator_code": source_id,
                    "source_id": row["source_id"],
                    "source_name": row["source_name"],
                },
                "result_id": _result_id("world_bank", source_id),
                "result_type": "statistical_indicator",
                "source": "world_bank",
                "source_id": source_id,
                "title": str(row["name_tr"]),
                "updated_at": wdi_manifest["retrieved_at"],
                "url": f"https://data.worldbank.org/indicator/{source_id}",
            }
        )

    holidays_manifest = json.loads(
        (holidays_dir / "SNAPSHOT.json").read_text(encoding="utf-8")
    )
    snapshot_hashes["federated_tr_public_holidays"] = holidays_manifest["content_hash"]
    for row in _read_jsonl(holidays_dir / "holidays.jsonl"):
        source_id = f"{row['date']}:{row['name']}"
        records.append(
            {
                "license": holidays_manifest["license"],
                "metadata": {
                    "category": row["category"],
                    "date": row["date"],
                    "duration": row["duration"],
                    "starts_at": row["starts_at"],
                },
                "result_id": _result_id("official_calendar", source_id),
                "result_type": "public_holiday",
                "source": "official_calendar",
                "source_id": source_id,
                "title": str(row["name"]),
                "updated_at": holidays_manifest["retrieved_at"],
                "url": holidays_manifest["sources"][0],
            }
        )

    by_id = {record["result_id"]: record for record in records}

    def search(arguments: Mapping[str, Any]) -> dict[str, Any]:
        query = _key(str(arguments["query"]))
        sources = {str(item) for item in arguments.get("sources", [])}
        unknown_sources = sources - {"geonames", "world_bank", "official_calendar"}
        if unknown_sources:
            raise ToolExecutionError(
                f"desteklenmeyen web metadata kaynağı: {sorted(unknown_sources)}",
                status_code=422,
            )
        result_type = str(arguments.get("result_type", "all"))
        limit = int(arguments.get("limit", 5))
        matches = [
            record
            for record in records
            if query in _key(f"{record['title']} {record['source_id']}")
            and (not sources or record["source"] in sources)
            and (result_type == "all" or record["result_type"] == result_type)
        ]
        matches.sort(
            key=lambda record: (
                0 if query == _key(str(record["title"])) else 1,
                record["source"],
                record["title"],
            )
        )
        safe_results = [
            {
                key: record[key]
                for key in (
                    "license",
                    "result_id",
                    "result_type",
                    "source",
                    "title",
                    "updated_at",
                    "url",
                )
            }
            for record in matches[:limit]
        ]
        return {"count": len(safe_results), "results": safe_results}

    def get_result_metadata(arguments: Mapping[str, Any]) -> dict[str, Any]:
        result_id = str(arguments["result_id"])
        record = by_id.get(result_id)
        if record is None:
            raise ToolExecutionError(
                f"web metadata sonucu bulunamadı: {result_id}",
                status_code=404,
            )
        return dict(record)

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes=snapshot_hashes,
        bindings=(
            LocalToolBinding(SEARCH, search),
            LocalToolBinding(GET_RESULT_METADATA, get_result_metadata),
        ),
    )
