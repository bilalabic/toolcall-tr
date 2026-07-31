"""USGS FDSN Event GeoJSON adaptörü."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://earthquake.usgs.gov"
PROVIDER = "usgs_earthquake"
NAMESPACE = "usgs_earthquake"
LICENSE = "PUBLIC-DOMAIN-US"
ATTRIBUTION = "U.S. Geological Survey"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="fdsn-event-1/2026-07",
    operation_id="query",
    upstream_url=f"{BASE_URL}/fdsnws/event/1/query",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params: dict[str, Any] = {
        "format": "geojson",
        "starttime": arguments["start_date"],
        "endtime": arguments["end_date"],
        "minmagnitude": arguments.get("minimum_magnitude", 0),
        "limit": arguments.get("limit", 20),
        "orderby": "time",
    }
    if arguments.get("latitude") is not None:
        params.update(
            {
                "latitude": arguments["latitude"],
                "longitude": arguments["longitude"],
                "maxradiuskm": arguments["radius_km"],
            }
        )
    return httpx.Request("GET", f"{base_url.rstrip('/')}/fdsnws/event/1/query", params=params)


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ToolExecutionError("USGS GeoJSON features alanı eksik")
    results: list[dict[str, Any]] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            continue
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 3:
            continue
        results.append(
            {
                "event_id": str(feature.get("id") or ""),
                "time_ms": int(props["time"]),
                "magnitude": float(props["mag"]),
                "place": str(props.get("place") or ""),
                "longitude": float(coords[0]),
                "latitude": float(coords[1]),
                "depth_km": float(coords[2]),
                "detail_url": str(props.get("url") or ""),
            }
        )
    results.sort(key=lambda item: (-item["time_ms"], item["event_id"]))
    return {"count": len(results), "results": results}


SEARCH_EARTHQUAKES = ToolSpec(
    tool_id="earthquake.search_earthquakes",
    provider=PROVIDER,
    name="search_earthquakes",
    description_tr="USGS kataloğunda tarih, büyüklük ve isteğe bağlı konuma göre deprem arar.",
    parameters=(
        ParamSpec(name="start_date", type="string", description_tr="Başlangıç tarihi.", required=True),
        ParamSpec(name="end_date", type="string", description_tr="Bitiş tarihi.", required=True),
        ParamSpec(
            name="minimum_magnitude",
            type="number",
            description_tr="En düşük deprem büyüklüğü.",
            has_default=True,
            default=0,
            minimum=-2,
            maximum=10,
        ),
        ParamSpec(name="latitude", type="number", description_tr="Merkez enlemi.", minimum=-90, maximum=90),
        ParamSpec(name="longitude", type="number", description_tr="Merkez boylamı.", minimum=-180, maximum=180),
        ParamSpec(name="radius_km", type="number", description_tr="Arama yarıçapı (km).", minimum=1, maximum=20000),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="En fazla sonuç.",
            has_default=True,
            default=20,
            minimum=1,
            maximum=100,
        ),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Deprem sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].event_id", type="string", description_tr="USGS olay kimliği.", semantic_type="earthquake_id"),
        OutputField(path="results[*].magnitude", type="number", description_tr="Deprem büyüklüğü."),
        OutputField(path="results[*].place", type="string", description_tr="Yer açıklaması."),
        OutputField(path="results[*].time_ms", type="integer", description_tr="Unix zaman damgası (ms)."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_EARTHQUAKES,)
adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(ToolBinding(SEARCH_EARTHQUAKES, _request, normalize),),
)
