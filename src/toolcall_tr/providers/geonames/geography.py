"""GeoNames Türkiye snapshot'ı üzerinde deterministik coğrafya araçları."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from toolcall_tr.canonical import sha256_hex
from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import (
    LocalProviderAdapter,
    LocalToolBinding,
    ToolExecutionError,
)
from toolcall_tr.turkish.text import ascii_fold_tr, casefold_tr

__all__ = [
    "FIND_NEARBY_PLACES",
    "GET_PLACE",
    "LOOKUP_POSTAL_CODE",
    "PROVIDER",
    "SEARCH_PLACES",
    "TOOLS",
    "build_adapter",
    "default_snapshot_dir",
]

PROVIDER = "geonames_tr"
LICENSE = "CC-BY-4.0"
ATTRIBUTION = "GeoNames geographical database, CC BY 4.0"

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="geonames_tr/2026-07-29",
    upstream_url="https://download.geonames.org/export/",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def default_snapshot_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "snapshots" / "geonames_tr"


def _search_key(value: str) -> str:
    return ascii_fold_tr(casefold_tr(value)).casefold()


SEARCH_PLACES = ToolSpec(
    tool_id="geo.search_places",
    provider=PROVIDER,
    name="search_places",
    description_tr=(
        "Türkiye'nin 81 il merkezini Türkçe veya ASCII yazımla arar; "
        "sonuçlar GeoNames kimliği ve koordinat taşır."
    ),
    parameters=(
        ParamSpec(
            name="query",
            type="string",
            description_tr="Aranacak il merkezi adı.",
            required=True,
            semantic_type="location_query",
            min_length=2,
            max_length=80,
        ),
        ParamSpec(
            name="province_codes",
            type="array",
            item_type="string",
            description_tr="İsteğe bağlı iki haneli il kodu filtresi.",
            required=False,
            semantic_type="province_code",
            min_items=1,
            max_items=10,
        ),
        ParamSpec(
            name="sort_by",
            type="string",
            description_tr="Sonuç sıralaması.",
            enum=["relevance", "population"],
            has_default=True,
            default="relevance",
        ),
        ParamSpec(
            name="include_alternate_names",
            type="boolean",
            description_tr="Sonuçlarda eş anlamlı ve tarihsel adları da döndür.",
            has_default=True,
            default=False,
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
            description_tr="Eşleşen sonuç sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].geoname_id",
            type="integer",
            description_tr="GeoNames kayıt kimliği.",
            semantic_type="place_id",
        ),
        OutputField(
            path="results[*].name",
            type="string",
            description_tr="İl merkezi adı.",
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
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_PLACE = ToolSpec(
    tool_id="geo.get_place",
    provider=PROVIDER,
    name="get_place",
    description_tr="GeoNames kimliğiyle Türkiye'deki bir il merkezinin ayrıntılarını getirir.",
    parameters=(
        ParamSpec(
            name="geoname_id",
            type="integer",
            description_tr="GeoNames kayıt kimliği.",
            required=True,
            semantic_type="place_id",
            minimum=1,
        ),
    ),
    outputs=(
        OutputField(
            path="geoname_id",
            type="integer",
            description_tr="GeoNames kayıt kimliği.",
            semantic_type="place_id",
        ),
        OutputField(
            path="name",
            type="string",
            description_tr="İl merkezi adı.",
            semantic_type="location_name",
        ),
        OutputField(
            path="timezone",
            type="string",
            description_tr="IANA saat dilimi.",
            semantic_type="timezone",
        ),
        OutputField(
            path="population",
            type="integer",
            description_tr="GeoNames nüfus değeri.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    source=_SOURCE,
)

FIND_NEARBY_PLACES = ToolSpec(
    tool_id="geo.find_nearby_places",
    provider=PROVIDER,
    name="find_nearby_places",
    description_tr=(
        "Verilen koordinata belirli yarıçap içinde kalan Türkiye il merkezlerini "
        "kuş uçuşu uzaklığıyla sıralar."
    ),
    parameters=(
        ParamSpec(
            name="latitude",
            type="number",
            description_tr="WGS84 enlem.",
            required=True,
            semantic_type="latitude",
            minimum=-90,
            maximum=90,
        ),
        ParamSpec(
            name="longitude",
            type="number",
            description_tr="WGS84 boylam.",
            required=True,
            semantic_type="longitude",
            minimum=-180,
            maximum=180,
        ),
        ParamSpec(
            name="radius_km",
            type="number",
            description_tr="Arama yarıçapı, kilometre.",
            minimum=1,
            maximum=1000,
            has_default=True,
            default=100,
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Döndürülecek en fazla il merkezi.",
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
            description_tr="Yarıçap içinde bulunan il merkezi sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].geoname_id",
            type="integer",
            description_tr="GeoNames kayıt kimliği.",
            semantic_type="place_id",
        ),
        OutputField(
            path="results[*].name",
            type="string",
            description_tr="İl merkezi adı.",
            semantic_type="location_name",
        ),
        OutputField(
            path="results[*].distance_km",
            type="number",
            description_tr="Koordinata kuş uçuşu uzaklık.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

LOOKUP_POSTAL_CODE = ToolSpec(
    tool_id="geo.lookup_postal_code",
    provider=PROVIDER,
    name="lookup_postal_code",
    description_tr="Beş haneli Türkiye posta kodunu il ve ilçe metadata'sıyla eşleştirir.",
    parameters=(
        ParamSpec(
            name="postal_code",
            type="string",
            description_tr="Beş haneli Türkiye posta kodu.",
            required=True,
            semantic_type="postal_code",
            pattern=r"^[0-9]{5}$",
            min_length=5,
            max_length=5,
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Aynı posta kodu için döndürülecek en fazla il/ilçe grubu.",
            minimum=1,
            maximum=20,
            has_default=True,
            default=10,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Eşleşen il/ilçe grubu sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].postal_code",
            type="string",
            description_tr="Posta kodu.",
            semantic_type="postal_code",
        ),
        OutputField(
            path="results[*].province",
            type="string",
            description_tr="İl adı.",
            semantic_type="location_name",
        ),
        OutputField(
            path="results[*].district",
            type="string",
            description_tr="İlçe adı.",
            semantic_type="location_name",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (
    SEARCH_PLACES,
    GET_PLACE,
    FIND_NEARBY_PLACES,
    LOOKUP_POSTAL_CODE,
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_adapter(snapshot_dir: Path | None = None) -> LocalProviderAdapter:
    directory = snapshot_dir or default_snapshot_dir()
    manifest = json.loads((directory / "SNAPSHOT.json").read_text(encoding="utf-8"))
    files = manifest["files"]

    places_path = directory / "places.jsonl"
    postal_path = directory / "postal_codes.jsonl"
    hashes = {
        "geonames_tr_places": sha256_hex(places_path.read_bytes()),
        "geonames_tr_postal_codes": sha256_hex(postal_path.read_bytes()),
    }
    expected = {
        "geonames_tr_places": files["places.jsonl"]["content_hash"],
        "geonames_tr_postal_codes": files["postal_codes.jsonl"]["content_hash"],
    }
    if hashes != expected:
        raise ValueError(f"GeoNames snapshot hash uyuşmazlığı: {hashes!r} != {expected!r}")

    places = _load_jsonl(places_path)
    postal_rows = _load_jsonl(postal_path)
    if len(places) != int(files["places.jsonl"]["row_count"]):
        raise ValueError("GeoNames yer snapshot satır sayısı manifest ile uyuşmuyor")
    if len(postal_rows) != int(files["postal_codes.jsonl"]["row_count"]):
        raise ValueError("GeoNames posta snapshot satır sayısı manifest ile uyuşmuyor")

    place_by_id = {int(row["geoname_id"]): row for row in places}
    postal_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in postal_rows:
        postal_by_code.setdefault(str(row["postal_code"]), []).append(row)

    def search_places(arguments: Mapping[str, Any]) -> dict[str, Any]:
        query = _search_key(str(arguments["query"]))
        province_codes = {str(item) for item in arguments.get("province_codes", [])}
        sort_by = str(arguments.get("sort_by", "relevance"))
        include_alternate = bool(arguments.get("include_alternate_names", False))
        limit = int(arguments.get("limit", 5))

        matches: list[tuple[int, dict[str, Any]]] = []
        for row in places:
            if province_codes and str(row["admin1_code"]) not in province_codes:
                continue
            names = [str(row["name"]), str(row["ascii_name"]), *row["alternate_names"]]
            keys = [_search_key(name) for name in names]
            if query not in " ".join(keys):
                continue
            score = 0 if query in keys[:2] else 1
            matches.append((score, row))

        if sort_by == "population":
            matches.sort(key=lambda item: (-int(item[1]["population"]), item[1]["name"]))
        else:
            matches.sort(
                key=lambda item: (
                    item[0],
                    -int(item[1]["population"]),
                    item[1]["name"],
                )
            )

        results: list[dict[str, Any]] = []
        for _, row in matches[:limit]:
            result = {
                key: row[key]
                for key in (
                    "admin1_code",
                    "ascii_name",
                    "country_code",
                    "geoname_id",
                    "latitude",
                    "longitude",
                    "name",
                    "population",
                    "timezone",
                )
            }
            # Canlı sağlayıcı isteklerinde kararlı cassette anahtarları için
            # WGS84 koordinatlarını yaklaşık 11 metre hassasiyete sabitle.
            result["latitude"] = round(float(result["latitude"]), 4)
            result["longitude"] = round(float(result["longitude"]), 4)
            if include_alternate:
                result["alternate_names"] = row["alternate_names"]
            results.append(result)
        return {"count": len(results), "results": results}

    def get_place(arguments: Mapping[str, Any]) -> dict[str, Any]:
        geoname_id = int(arguments["geoname_id"])
        row = place_by_id.get(geoname_id)
        if row is None:
            raise ToolExecutionError(
                f"GeoNames kaydı bulunamadı: {geoname_id}",
                status_code=404,
            )
        return dict(row)

    def find_nearby_places(arguments: Mapping[str, Any]) -> dict[str, Any]:
        latitude = float(arguments["latitude"])
        longitude = float(arguments["longitude"])
        radius_km = float(arguments.get("radius_km", 100))
        limit = int(arguments.get("limit", 5))
        results = []
        for row in places:
            distance = _haversine_km(
                latitude,
                longitude,
                float(row["latitude"]),
                float(row["longitude"]),
            )
            if distance <= radius_km:
                results.append(
                    {
                        "distance_km": round(distance, 3),
                        "geoname_id": row["geoname_id"],
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "name": row["name"],
                    }
                )
        results.sort(key=lambda row: (row["distance_km"], row["name"]))
        return {"count": len(results[:limit]), "results": results[:limit]}

    def lookup_postal_code(arguments: Mapping[str, Any]) -> dict[str, Any]:
        postal_code = str(arguments["postal_code"])
        limit = int(arguments.get("limit", 10))
        results = [dict(row) for row in postal_by_code.get(postal_code, [])[:limit]]
        return {"count": len(results), "results": results}

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes=hashes,
        bindings=(
            LocalToolBinding(SEARCH_PLACES, search_places),
            LocalToolBinding(GET_PLACE, get_place),
            LocalToolBinding(FIND_NEARBY_PLACES, find_nearby_places),
            LocalToolBinding(LOOKUP_POSTAL_CODE, lookup_postal_code),
        ),
    )
