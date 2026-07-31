"""MET Norway sağlayıcı sınırı."""

from __future__ import annotations

from pathlib import Path

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import StepOutcome
from toolcall_tr.pipeline.environment import build_default_registry, open_default_environment
from toolcall_tr.providers.met.locations import SEARCH_LOCATION
from toolcall_tr.providers.met.locations import build_adapter as build_location_adapter
from toolcall_tr.providers.met.weather import (
    GET_CURRENT_WEATHER,
    adapter,
    normalize_current_weather,
    normalize_weather_forecast,
)


def _payload() -> dict[str, object]:
    return {
        "geometry": {"type": "Point", "coordinates": [39.22, 38.68, 1067]},
        "properties": {
            "timeseries": [
                {
                    "time": "2026-07-29T09:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 31.2,
                                "relative_humidity": 22.0,
                                "wind_speed": 3.4,
                                "wind_from_direction": 245.0,
                            }
                        }
                    },
                },
                {
                    "time": "2026-07-29T10:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 32.0,
                                "relative_humidity": 20.0,
                                "wind_speed": 3.8,
                                "wind_from_direction": 250.0,
                            }
                        }
                    },
                },
            ]
        },
    }


def test_koordinatlar_dort_ondaliga_sabitlenir() -> None:
    binding = adapter.binding(GET_CURRENT_WEATHER.tool_id)
    assert binding is not None
    request = binding.build_request(
        {"latitude": 38.681234, "longitude": 39.223456, "altitude": 1066.6},
        adapter.base_url or "",
    )
    assert request.url.params["lat"] == "38.6812"
    assert request.url.params["lon"] == "39.2235"
    assert request.url.params["altitude"] == "1067"


def test_current_ilk_zaman_adimini_alir() -> None:
    result = normalize_current_weather(_payload())
    assert result["current"]["temperature_c"] == 31.2
    assert result["location"] == {"latitude": 38.68, "longitude": 39.22, "altitude_m": 1067}


def test_forecast_deterministik_saatlik_liste_uretir() -> None:
    result = normalize_weather_forecast(_payload())
    assert result["count"] == 2
    assert [row["time"] for row in result["hourly"]] == [
        "2026-07-29T09:00:00Z",
        "2026-07-29T10:00:00Z",
    ]


def test_default_registry_met_araclarini_icerir() -> None:
    registry = build_default_registry()
    assert registry.get("weather.search_location") is None
    assert registry.get("geo.search_places") is not None
    assert registry.require("weather.get_current_weather") == GET_CURRENT_WEATHER
    assert registry.get("weather.get_weather_forecast") is not None


def test_replay_cassette_yokken_aga_cikmaz(repo_root: Path) -> None:
    with open_default_environment(repo_root=repo_root) as environment:
        result = environment.executor_for("met_norway").execute(
            GET_CURRENT_WEATHER,
            {"latitude": 38.68, "longitude": 39.22},
        )
    assert result.outcome is StepOutcome.TRANSPORT_ERROR
    assert result.error is not None
    assert "Cassette bulunamadı" in result.error


def test_sehir_arama_turkce_ve_ascii_eslesir(repo_root: Path) -> None:
    executor = DerivedLocalExecutor(
        build_location_adapter(repo_root / "data" / "snapshots" / "tr_cities")
    )
    turkish = executor.execute(SEARCH_LOCATION, {"query": "Elazığ"})
    ascii_result = executor.execute(SEARCH_LOCATION, {"query": "Elazig"})
    assert turkish.outcome is StepOutcome.OK
    assert turkish.response == ascii_result.response
    assert turkish.response["results"][0]["name"] == "Elazığ"
