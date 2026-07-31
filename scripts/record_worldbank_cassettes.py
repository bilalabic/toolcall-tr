"""World Bank WDI pilot cassette'ini kaydeder."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.frankfurter import rates
from toolcall_tr.providers.izmir import ckan, eshot
from toolcall_tr.providers.met import weather
from toolcall_tr.providers.usgs import earthquakes
from toolcall_tr.providers.worldbank import indicators

ROOT = Path(__file__).resolve().parent.parent / "data" / "cassettes"
ARGS = {
    "country_codes": ["TUR"],
    "indicator_code": "SP.POP.TOTL",
    "start_year": 2010,
    "end_year": 2024,
}


def main() -> int:
    with build_http_runtime(
        indicators.adapter,
        cassette_root=ROOT,
        mode=CassetteMode.RECORD_MISSING,
        timeout=60.0,
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        result = runtime.executor.execute(indicators.GET_INDICATOR_TIME_SERIES, ARGS)
        if not result.succeeded:
            print(result.error, file=sys.stderr)
            return 1
        print(f"{result.response['count']} veri noktası")

    stores = [
        CassetteStore(ROOT, ckan.NAMESPACE, license=ckan.LICENSE, attribution=ckan.ATTRIBUTION),
        CassetteStore(
            ROOT,
            eshot.NAMESPACE,
            license=eshot.LICENSE,
            attribution=eshot.ATTRIBUTION,
            max_entries=eshot.MAX_CASSETTES,
        ),
        CassetteStore(ROOT, weather.NAMESPACE, license=weather.LICENSE, attribution=weather.ATTRIBUTION),
        CassetteStore(ROOT, rates.NAMESPACE, license=rates.LICENSE, attribution=rates.ATTRIBUTION),
        CassetteStore(
            ROOT,
            earthquakes.NAMESPACE,
            license=earthquakes.LICENSE,
            attribution=earthquakes.ATTRIBUTION,
        ),
        runtime.store,
    ]
    print(f"MANIFEST.json -> {write_manifest(ROOT, stores)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
