"""USGS deprem pilot cassette kaydı."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.frankfurter import rates
from toolcall_tr.providers.izmir import ckan, eshot
from toolcall_tr.providers.met import weather
from toolcall_tr.providers.usgs import earthquakes

ROOT = Path(__file__).resolve().parent.parent / "data" / "cassettes"
ARGS = {
    "start_date": "2026-07-20",
    "end_date": "2026-07-28",
    "minimum_magnitude": 3,
    "latitude": 38.6743,
    "longitude": 39.2232,
    "radius_km": 300,
    "limit": 20,
}


def main() -> int:
    with build_http_runtime(
        earthquakes.adapter, cassette_root=ROOT, mode=CassetteMode.RECORD_MISSING
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        result = runtime.executor.execute(earthquakes.SEARCH_EARTHQUAKES, ARGS)
        if not result.succeeded:
            print(result.error, file=sys.stderr)
            return 1
        print(f"{result.response['count']} deprem")
    stores = [
        CassetteStore(ROOT, ckan.NAMESPACE, license=ckan.LICENSE, attribution=ckan.ATTRIBUTION),
        CassetteStore(ROOT, eshot.NAMESPACE, license=eshot.LICENSE, attribution=eshot.ATTRIBUTION),
        CassetteStore(ROOT, weather.NAMESPACE, license=weather.LICENSE, attribution=weather.ATTRIBUTION),
        CassetteStore(ROOT, rates.NAMESPACE, license=rates.LICENSE, attribution=rates.ATTRIBUTION),
        runtime.store,
    ]
    print(write_manifest(ROOT, stores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
