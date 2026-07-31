"""ESHOT gerçek zamanlı cassette'lerini kaydeder.

> **LİSANS:** `openapi.izmir.bel.tr` için beyan edilmiş lisans yoktur
> (`LICENSE-DATA` § 3). Bu yüzden kayıt sayısı kasıtlı olarak sınırlıdır ve
> `CassetteStore.max_entries` bunu kodda zorlar.

Durak seçimi dondurulmuş snapshot'tan **deterministik** olarak yapılır: merkezi
duraklar (yaklaşan araç bulma olasılığı yüksek) ve kırsal duraklar (boş sonuç
vakası) birlikte alınır.

    uv run python scripts/record_eshot_cassettes.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.izmir import eshot
from toolcall_tr.providers.izmir.stops import haversine_m, load_stop_table

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_ROOT = REPO_ROOT / "data" / "cassettes"

#: Konak Meydanı -- merkez referansı.
KONAK = (38.4192, 27.1287)

#: Merkeze en yakın kaç durak denensin (araç bulma olasılığı yüksek).
CENTRAL_COUNT = 10
#: En uzak kaç durak denensin (boş sonuç vakası için).
REMOTE_COUNT = 4


def main() -> int:
    table = load_stop_table()
    ranked = sorted(
        table.stops,
        key=lambda s: haversine_m(KONAK[0], KONAK[1], s.latitude, s.longitude),
    )
    # Aynı DURAK_ID birden fazla satırda olabilir; tekilleştir.
    seen: set[int] = set()
    central: list[int] = []
    for stop in ranked:
        if stop.stop_id not in seen:
            seen.add(stop.stop_id)
            central.append(stop.stop_id)
        if len(central) >= CENTRAL_COUNT:
            break

    remote = [s.stop_id for s in ranked[-REMOTE_COUNT:]]
    stop_ids = central + remote

    empty = 0
    with_buses = 0
    failures = 0

    with build_http_runtime(
        eshot.adapter,
        cassette_root=CASSETTE_ROOT,
        mode=CassetteMode.RECORD,
        max_entries=eshot.MAX_CASSETTES,
    ) as runtime:
        for stop_id in stop_ids:
            result = runtime.executor.execute(eshot.GET_APPROACHING_BUSES, {"stop_id": stop_id})
            if not result.succeeded:
                failures += 1
                print(f"  [KIRIK] {stop_id:>6}  {result.outcome.value}: {result.error}")
                continue
            count = result.response["count"]
            if count == 0:
                empty += 1
                marker = "BOŞ"
            else:
                with_buses += 1
                marker = f"{count} araç"
            print(f"  [  ok ] {stop_id:>6}  {marker}")
            time.sleep(0.6)  # nazik davran

        print(f"\n{len(runtime.store)} kayıt: {runtime.store.dir}")
        print(f"  araç bulunan: {with_buses}   boş sonuç: {empty}   kırık: {failures}")

        if with_buses == 0:
            print(
                "\nUYARI: hiçbir durakta yaklaşan araç yok. Gece saatlerinde normaldir;\n"
                "dolu yanıt kaydı için gündüz tekrar çalıştırın.",
                file=sys.stderr,
            )
        if empty == 0:
            print(
                "\nUYARI: boş sonuç vakası kaydedilemedi. `allow_empty_result` senaryosu\n"
                "için en az bir boş yanıt gerekir.",
                file=sys.stderr,
            )

    write_manifest(
        CASSETTE_ROOT,
        [runtime.store],
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
