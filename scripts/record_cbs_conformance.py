"""Canlı CBS "yakın duraklar" endpoint'inden conformance örneklemi kaydeder.

Bu kayıtlar **veri setine girmez**. Tek amaçları, `find_nearby_stops`'un yerel
haversine implementasyonunun belediyenin kendi servisiyle ne kadar uyuştuğunu
ölçmek ve bu sayıyı dataset card'a yazabilmektir. "Yerel hesapladık" demek ile
"yerel hesapladık ve N/M sorguda belediye servisiyle aynı sonucu verdi" demek
arasındaki fark, eleştiriye açık olmakla olmamak arasındaki farktır.

LİSANS: `openapi.izmir.bel.tr` ayrı bir host ve beyan edilmiş lisansı yok.
Bkz. LICENSE-DATA § 3. Bu yüzden örneklem küçük tutulur ve `tests/fixtures/`
altında, veri setinden ayrı saklanır.

    uv run python scripts/record_cbs_conformance.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "data" / "snapshots" / "eshot_stops" / "stops.jsonl"
OUT = REPO_ROOT / "tests" / "fixtures" / "cbs_conformance.json"

ENDPOINT = "https://openapi.izmir.bel.tr/api/ibb/cbs/noktayayakinduraklar"
SAMPLE_SIZE = 25


def load_stops() -> list[dict[str, Any]]:
    return [json.loads(line) for line in SNAPSHOT.read_text(encoding="utf-8").splitlines() if line]


def sample_points(stops: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Tablo boyunca eşit aralıklı örnekleme -- rastgele değil, deterministik."""
    step = max(1, len(stops) // count)
    return [stops[i * step] for i in range(count) if i * step < len(stops)]


def query(client: httpx.Client, lat: float, lon: float, *, prefixed: bool) -> Any:
    crs = "EPSG:4326" if prefixed else "4326"
    response = client.get(
        ENDPOINT,
        params={"x": lon, "y": lat, "inCoordSys": crs, "outCoordSys": crs},
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    if not SNAPSHOT.is_file():
        print("önce scripts/fetch_stops_snapshot.py çalıştırın", file=sys.stderr)
        return 1

    stops = load_stops()
    points = sample_points(stops, SAMPLE_SIZE)
    headers = {"User-Agent": "toolcall-tr/0.1 (+https://github.com/toolcall-tr/toolcall-tr)"}

    samples: list[dict[str, Any]] = []
    with httpx.Client(timeout=25.0, headers=headers) as client:
        for index, stop in enumerate(points, start=1):
            lat, lon = stop["ENLEM"], stop["BOYLAM"]
            try:
                upstream = query(client, lat, lon, prefixed=True)
            except httpx.HTTPError as exc:
                print(f"  [{index:>2}] ATLANDI {stop['DURAK_ID']}: {exc}")
                continue
            samples.append(
                {
                    "query": {"lat": lat, "lon": lon},
                    "origin_stop_id": stop["DURAK_ID"],
                    "origin_stop_name": stop["DURAK_ADI"],
                    "upstream": upstream,
                }
            )
            print(
                f"  [{index:>2}] {stop['DURAK_ID']:>6} {stop['DURAK_ADI'][:28]:<28} "
                f"-> {len(upstream)} durak"
            )
            time.sleep(0.5)  # nazik davran: sınır beyan edilmemiş ama yüklenmesin

        # EPSG tuzağının kanıtı: aynı nokta, prefix'siz CRS.
        probe = points[0]
        trap: Any = None
        try:
            trap = query(client, probe["ENLEM"], probe["BOYLAM"], prefixed=False)
        except httpx.HTTPError as exc:
            print(f"tuzak sorgusu başarısız: {exc}")

    payload = {
        "_notice": (
            "openapi.izmir.bel.tr ayrı bir host ve beyan edilmiş lisansı yoktur "
            "(LICENSE-DATA § 3). Bu örneklem yalnızca conformance ölçümü içindir "
            "ve yayımlanan veri setine dâhil edilmez."
        ),
        "license": "UNDETERMINED",
        "endpoint": ENDPOINT,
        "recorded_at": datetime.now(UTC).date().isoformat(),
        "samples": samples,
        "epsg_trap": {
            "description": (
                "inCoordSys=4326 (prefix'siz) gönderildiğinde servis CRS'i sessizce "
                "yok sayar, girdiyi projeksiyon metresi kabul eder ve ilin bambaşka "
                "bir ucundan sonuç döner. Hata vermez."
            ),
            "query": {"lat": probe["ENLEM"], "lon": probe["BOYLAM"]},
            "origin_stop_name": probe["DURAK_ADI"],
            "response": trap,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"\n{len(samples)} örnek -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
