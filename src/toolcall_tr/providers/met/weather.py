"""MET Norway Locationforecast 2.0 adaptörü.

Canlı yanıt cassette'e eksiksiz yazılır; tool sonucuna yalnızca eğitim için
gerekli, kararlı alanlar alınır. Koordinatlar sağlayıcının şartı gereği en çok
dört ondalığa yuvarlanır.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

__all__ = [
    "BASE_URL",
    "GET_CURRENT_WEATHER",
    "GET_WEATHER_FORECAST",
    "TOOLS",
    "adapter",
    "normalize_current_weather",
    "normalize_weather_forecast",
]

BASE_URL = "https://api.met.no"
PROVIDER = "met_norway"
NAMESPACE = "met_norway"
LICENSE = "CC-BY-4.0"
ATTRIBUTION = "Norwegian Meteorological Institute (MET Norway), CC BY 4.0"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="locationforecast-2.0/2026-07",
    operation_id="locationforecast_compact",
    upstream_url=f"{BASE_URL}/weatherapi/locationforecast/2.0/compact",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

_COORDINATES = (
    ParamSpec(
        name="latitude",
        type="number",
        description_tr="Konumun WGS84 enlemi.",
        required=True,
        semantic_type="latitude",
        minimum=-90,
        maximum=90,
    ),
    ParamSpec(
        name="longitude",
        type="number",
        description_tr="Konumun WGS84 boylamı.",
        required=True,
        semantic_type="longitude",
        minimum=-180,
        maximum=180,
    ),
    ParamSpec(
        name="altitude",
        type="number",
        description_tr="İsteğe bağlı rakım (metre).",
        required=False,
        minimum=-500,
        maximum=9000,
    ),
)


def _build_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params: dict[str, int | float] = {
        "lat": round(float(arguments["latitude"]), 4),
        "lon": round(float(arguments["longitude"]), 4),
    }
    if arguments.get("altitude") is not None:
        params["altitude"] = round(float(arguments["altitude"]))
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/weatherapi/locationforecast/2.0/compact",
        params=params,
    )


def _timeseries(payload: Any) -> tuple[dict[str, Any], list[Any]]:
    if not isinstance(payload, dict):
        raise ToolExecutionError(f"beklenen nesne, gelen {type(payload).__name__}")
    geometry = payload.get("geometry")
    properties = payload.get("properties")
    if not isinstance(geometry, dict) or not isinstance(properties, dict):
        raise ToolExecutionError("Locationforecast yanıtında geometry/properties eksik")
    series = properties.get("timeseries")
    if not isinstance(series, list) or not series:
        raise ToolExecutionError("Locationforecast timeseries boş veya geçersiz")
    return geometry, series


def _instant(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ToolExecutionError("timeseries öğesi nesne değil")
    data = item.get("data")
    if not isinstance(data, dict):
        raise ToolExecutionError("timeseries.data eksik")
    instant = data.get("instant")
    if not isinstance(instant, dict) or not isinstance(instant.get("details"), dict):
        raise ToolExecutionError("timeseries.data.instant.details eksik")
    details = instant["details"]
    return {
        "time": str(item.get("time") or ""),
        "temperature_c": details.get("air_temperature"),
        "relative_humidity_percent": details.get("relative_humidity"),
        "wind_speed_mps": details.get("wind_speed"),
        "wind_direction_degrees": details.get("wind_from_direction"),
    }


def _location(geometry: dict[str, Any]) -> dict[str, Any]:
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ToolExecutionError("geometry.coordinates geçersiz")
    result: dict[str, Any] = {
        "latitude": coordinates[1],
        "longitude": coordinates[0],
    }
    if len(coordinates) >= 3:
        result["altitude_m"] = coordinates[2]
    return result


def normalize_current_weather(payload: Any) -> dict[str, Any]:
    geometry, series = _timeseries(payload)
    return {"location": _location(geometry), "current": _instant(series[0])}


def normalize_weather_forecast(payload: Any) -> dict[str, Any]:
    geometry, series = _timeseries(payload)
    hourly = [_instant(item) for item in series]
    return {"location": _location(geometry), "count": len(hourly), "hourly": hourly}


GET_CURRENT_WEATHER = ToolSpec(
    tool_id="weather.get_current_weather",
    provider=PROVIDER,
    name="get_current_weather",
    description_tr="Belirtilen koordinat için en güncel hava durumu ölçümünü getirir.",
    parameters=_COORDINATES,
    outputs=(
        OutputField(path="current.time", type="string", description_tr="Ölçüm zamanı."),
        OutputField(
            path="current.temperature_c",
            type="number",
            description_tr="Hava sıcaklığı (°C).",
        ),
        OutputField(
            path="current.wind_speed_mps",
            type="number",
            description_tr="Rüzgâr hızı (m/s).",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

GET_WEATHER_FORECAST = ToolSpec(
    tool_id="weather.get_weather_forecast",
    provider=PROVIDER,
    name="get_weather_forecast",
    description_tr="Belirtilen koordinat için saatlik hava tahminini getirir.",
    parameters=_COORDINATES,
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Saatlik tahmin kaydı sayısı.",
            semantic_type="result_count",
        ),
        OutputField(path="hourly[*].time", type="string", description_tr="Tahmin zamanı."),
        OutputField(
            path="hourly[*].temperature_c",
            type="number",
            description_tr="Tahmin edilen sıcaklık (°C).",
        ),
        OutputField(
            path="hourly[*].relative_humidity_percent",
            type="number",
            description_tr="Tahmin edilen bağıl nem (%).",
        ),
        OutputField(
            path="hourly[*].wind_speed_mps",
            type="number",
            description_tr="Tahmin edilen rüzgâr hızı (m/s).",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (GET_CURRENT_WEATHER, GET_WEATHER_FORECAST)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(GET_CURRENT_WEATHER, _build_request, normalize_current_weather),
        ToolBinding(GET_WEATHER_FORECAST, _build_request, normalize_weather_forecast),
    ),
)
