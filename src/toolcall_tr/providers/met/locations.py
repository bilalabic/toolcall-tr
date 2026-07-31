"""Dondurulmuş Türkiye şehir snapshot'ı üzerinde yerel konum arama."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from toolcall_tr.canonical import sha256_hex
from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import LocalProviderAdapter, LocalToolBinding
from toolcall_tr.turkish.text import ascii_fold_tr, casefold_tr

__all__ = ["SEARCH_LOCATION", "TOOLS", "build_adapter", "default_snapshot_dir"]

PROVIDER = "location_snapshot"
LICENSE = "CC-BY-4.0"
ATTRIBUTION = (
    "GeoNames geographical database, CC BY 4.0; "
    "ToolCall-TR tarafından seçilmiş pilot alt küme."
)

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="tr_cities/2026-07-pilot",
    upstream_url="https://download.geonames.org/export/dump/",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def default_snapshot_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "snapshots" / "tr_cities"


def _search_key(value: str) -> str:
    return ascii_fold_tr(casefold_tr(value)).casefold()


SEARCH_LOCATION = ToolSpec(
    tool_id="weather.search_location",
    provider=PROVIDER,
    name="search_location",
    description_tr="Türkiye'deki bir şehir adını koordinat ve ülke koduyla eşleştirir.",
    parameters=(
        ParamSpec(
            name="query",
            type="string",
            description_tr="Aranacak şehir adı.",
            required=True,
            semantic_type="location_query",
            min_length=2,
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Döndürülecek en fazla eşleşme.",
            minimum=1,
            maximum=10,
            has_default=True,
            default=5,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Eşleşen konum sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].name",
            type="string",
            description_tr="Şehir adı.",
            semantic_type="location_name",
        ),
        OutputField(
            path="results[*].latitude",
            type="number",
            description_tr="WGS84 enlem.",
            semantic_type="latitude",
        ),
        OutputField(
            path="results[*].longitude",
            type="number",
            description_tr="WGS84 boylam.",
            semantic_type="longitude",
        ),
        OutputField(
            path="results[*].country_code",
            type="string",
            description_tr="ISO 3166-1 alpha-2 ülke kodu.",
            semantic_type="country_code",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_LOCATION,)


def build_adapter(snapshot_dir: Path | None = None) -> LocalProviderAdapter:
    directory = snapshot_dir or default_snapshot_dir()
    data_path = directory / "locations.jsonl"
    manifest = json.loads((directory / "SNAPSHOT.json").read_text(encoding="utf-8"))
    content_hash = sha256_hex(data_path.read_bytes())
    if content_hash != manifest["content_hash"]:
        raise ValueError(
            f"şehir snapshot hash uyuşmazlığı: {manifest['content_hash']} != {content_hash}"
        )
    rows = [
        json.loads(line)
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != int(manifest["row_count"]):
        raise ValueError("şehir snapshot satır sayısı manifest ile uyuşmuyor")

    def search(arguments: Mapping[str, Any]) -> dict[str, Any]:
        query = _search_key(str(arguments["query"]))
        limit = int(arguments.get("limit", 5))
        matched = [row for row in rows if query in _search_key(str(row["name"]))]
        matched.sort(key=lambda row: (-int(row["population"]), str(row["name"])))
        results = [
            {
                "name": row["name"],
                "country_code": row["country_code"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }
            for row in matched[:limit]
        ]
        return {"count": len(results), "results": results}

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes={"tr_cities": content_hash},
        bindings=(LocalToolBinding(SEARCH_LOCATION, search),),
    )
