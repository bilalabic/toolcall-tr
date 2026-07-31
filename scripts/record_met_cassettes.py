"""MET Norway pilot cassette'lerini kontrollü biçimde kaydeder.

Normal pipeline ağa çıkmaz. Bu script yalnızca bildirilen koordinatları çeker,
kimlikli User-Agent kullanır ve tüm sağlayıcıları içeren manifesti yeniden
yazar.
"""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.met import weather

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_ROOT = REPO_ROOT / "data" / "cassettes"

CALLS = (
    (
        weather.GET_WEATHER_FORECAST,
        {"latitude": 38.6743, "longitude": 39.2232},
    ),
    (
        weather.GET_CURRENT_WEATHER,
        {"latitude": 41.0138, "longitude": 28.9497},
    ),
)


def _all_stores(met_store: CassetteStore) -> list[CassetteStore]:
    """Manifesti güncellerken diğer provider namespace'lerini kaybetme."""
    stores: list[CassetteStore] = []
    for path in sorted(item for item in CASSETTE_ROOT.iterdir() if item.is_dir()):
        stores.append(
            met_store
            if path.name == weather.NAMESPACE
            else CassetteStore(CASSETTE_ROOT, path.name)
        )
    return stores


def main() -> int:
    failures = 0
    with build_http_runtime(
        weather.adapter,
        cassette_root=CASSETTE_ROOT,
        mode=CassetteMode.RECORD_MISSING,
    ) as runtime:
        # api.met.no zaman zaman `Content-Encoding: gzip` başlığıyla
        # sıkıştırılmamış gövde döndürüyor. Kayıt işini deterministik tutmak
        # için bu küçük batch'te sıkıştırmasız aktarım iste.
        runtime.client.headers["Accept-Encoding"] = "identity"
        for tool, arguments in CALLS:
            result = runtime.executor.execute(tool, arguments)
            if not result.succeeded:
                failures += 1
                print(f"[KIRIK] {arguments}: {result.error}", file=sys.stderr)
                continue
            summary = (
                f"{result.response['count']} saat"
                if "count" in result.response
                else "güncel gözlem"
            )
            print(
                f"[ok] {tool.tool_id} "
                f"{arguments['latitude']:.4f},{arguments['longitude']:.4f} "
                f"-> {summary}"
            )

    digest = write_manifest(CASSETTE_ROOT, _all_stores(runtime.store))
    print(f"MANIFEST.json -> {digest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
