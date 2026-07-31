"""ESHOT durak tablosunu dondurulmuş snapshot olarak indirir.

`find_nearby_stops` bu snapshot üzerinde yerel haversine ile çalışır. Gerekçe:

1. Canlı `cbs/noktayayakinduraklar` endpoint'i ``inCoordSys=4326`` (prefix'siz)
   verildiğinde CRS'i **sessizce yok sayar** ve ilin bambaşka bir ucundan
   sonuç döner. Hata vermez -- yanlış cevap verir.
2. Dondurulmuş tablo beş yıl sonra da yeniden üretilebilir; belediye
   endpoint'i kaybolsa bile.
3. Tablo CC BY 4.0 ve koordinatları zaten temiz WGS84.

Snapshot yanında `SNAPSHOT.json` yazılır: kaynak kimliği, alınma tarihi, satır
sayısı, içerik hash'i, lisans ve atıf.

    uv run python scripts/fetch_stops_snapshot.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from toolcall_tr.canonical import sha256_of

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots" / "eshot_stops"

BASE = "https://acikveri.bizizmir.com/api/3/action/datastore_search"
RESOURCE_ID = "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
DATASET = "eshot-otobus-duraklari"
PAGE_SIZE = 1000

LICENSE = "CC-BY-4.0"
ATTRIBUTION = (
    "İzmir Büyükşehir Belediyesi Açık Veri Portalı, CC BY 4.0. "
    "Dondurulmuş ve değiştirilmiş alt küme."
)


def fetch_all(client: httpx.Client) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None

    while True:
        response = client.get(
            BASE,
            params={
                "resource_id": RESOURCE_ID,
                "limit": PAGE_SIZE,
                "offset": offset,
                # Sayfalama sırasında satır sırası garanti altında olmalı,
                # yoksa sayfalar arasında kayıt kaybolur veya tekrarlanır.
                "sort": "_id asc",
            },
        )
        response.raise_for_status()
        result = response.json()["result"]
        if total is None:
            total = int(result["total"])
            print(f"toplam {total} satır")
        batch = result["records"]
        if not batch:
            break
        records.extend(batch)
        offset += len(batch)
        print(f"  {len(records)}/{total}", end="\r")
        if len(records) >= total:
            break

    print()
    return records


def normalize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kayıtları sadeleştirir ve deterministik sıraya sokar.

    CKAN'ın iç `_id` alanı atılır: yeniden içe aktarımda değişebilir ve
    anlamsal bir bilgi taşımaz. Sıralama `DURAK_ID`'ye göre yapılır, böylece
    yeniden indirmede satır sırası değişse bile snapshot hash'i sabit kalır.
    """
    out: list[dict[str, Any]] = []
    for row in records:
        lines = str(row.get("DURAKTAN_GECEN_HATLAR") or "").strip()
        out.append(
            {
                "DURAK_ID": int(row["DURAK_ID"]),
                "DURAK_ADI": str(row["DURAK_ADI"]).strip(),
                "ENLEM": float(row["ENLEM"]),
                "BOYLAM": float(row["BOYLAM"]),
                "DURAKTAN_GECEN_HATLAR": lines,
            }
        )
    out.sort(key=lambda r: (r["DURAK_ID"], r["ENLEM"], r["BOYLAM"]))
    return out


def main() -> int:
    headers = {"User-Agent": "toolcall-tr/0.1 (+https://github.com/toolcall-tr/toolcall-tr)"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        raw = fetch_all(client)

    rows = normalize(raw)
    if not rows:
        print("HATA: hiç satır alınamadı", file=sys.stderr)
        return 1

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    (SNAPSHOT_DIR / "stops.jsonl").write_text(payload, encoding="utf-8", newline="\n")

    manifest = {
        "name": "eshot_stops",
        "source": {
            "portal": "https://acikveri.bizizmir.com",
            "dataset": DATASET,
            "resource_id": RESOURCE_ID,
            "endpoint": "datastore_search",
        },
        "retrieved_at": datetime.now(UTC).date().isoformat(),
        "row_count": len(rows),
        "content_hash": sha256_of(rows),
        "fields": sorted(rows[0]),
        "license": LICENSE,
        "license_url": "https://acikveri.bizizmir.com/tr/license",
        "attribution": ATTRIBUTION,
        "modifications": [
            "CKAN iç `_id` alanı çıkarıldı.",
            "Satırlar DURAK_ID'ye göre deterministik olarak sıralandı.",
            "ENLEM/BOYLAM float'a, DURAK_ID int'e çevrildi.",
        ],
    }
    (SNAPSHOT_DIR / "SNAPSHOT.json").write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"{len(rows)} satır -> {SNAPSHOT_DIR}")
    print(f"içerik hash: {manifest['content_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
