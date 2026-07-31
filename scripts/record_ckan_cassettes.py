"""İzmir CKAN cassette'lerini kaydeder.

Ağa çıkan **tek** yol budur; normal pipeline replay modunda çalışır ve ağ
erişimi kapalıdır.

Çağrı listesi bilinçli olarak bildirimseldir: hangi kayıtların neden var
olduğu kod içinde görünür kalsın ve yeniden kayıt deterministik olsun.

    uv run python scripts/record_ckan_cassettes.py

Kapsanan senaryolar: başarı, **boş sonuç**, **beklenen hata**. Son ikisi
kasıtlıdır -- yalnızca mutlu yolları kaydetmek, execution validator'ın en
ilginç vakaları hiç görmemesi demektir.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from toolcall_tr.execution.cassette import CassetteMode, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.izmir import ckan

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_ROOT = REPO_ROOT / "data" / "cassettes"

#: Doğrulanmış resource'lar. `eshot-otobus-duraklari` veri setinin tek
#: kaynağıdır ve `datastore_active: true`'dur -- yani üç adımlı kompozisyon
#: zinciri (arama -> metadata -> tablo) gerçekten yürür.
#:
#: NOT: `duraga-yaklasan-otobusler` veri setinin İKİ kaynağı da
#: `datastore_active: false`'tur (biri API, biri PDF). Zinciri oradan kurmak
#: sessizce çalışmayan bir ground-truth üretirdi.
STOPS_RESOURCE_ID = "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
STOPS_DATASET = "eshot-otobus-duraklari"
TAXI_RESOURCE_ID = "64a72577-5f4c-404c-8842-780d88f351df"
TAXI_DATASET = "taksi-durak-bilgileri"

#: (tool_id, argümanlar, bu kaydın neden var olduğu)
CALLS: list[tuple[str, dict[str, Any], str]] = [
    # -- arama --------------------------------------------------------------
    ("izmir.search_datasets", {"q": "otobüs durak"}, "kompozisyon zincirinin 1. adımı"),
    ("izmir.search_datasets", {"q": "otobüs"}, "temel arama"),
    ("izmir.search_datasets", {"q": "taksi durak"}, "ikinci zincirin 1. adımı"),
    # Türkçe eklemeli yapı: Solr kök bulma yapmıyor. "durak" -> 8 sonuç,
    # "durağı" -> 0. Ünsüz yumuşaması (k->ğ) + iyelik eki sorguyu boşa
    # çıkarıyor. İngilizceden türetilmiş veri setlerinin yakalayamadığı
    # gerçek bir hata modu; kasıtlı olarak kaydediliyor.
    ("izmir.search_datasets", {"q": "otobüs durağı"}, "BOŞ SONUÇ -- Türkçe ek morfolojisi"),
    ("izmir.search_datasets", {"q": "taksi durağı"}, "BOŞ SONUÇ -- aynı olgu, ikinci örnek"),
    ("izmir.search_datasets", {"q": "hava kalitesi"}, "çok kelimeli arama"),
    ("izmir.search_datasets", {"q": "otobüs", "rows": 3}, "sayfalama parametresi"),
    # Türkçe karakter normalizasyonu: Solr analyzer'ı ü/u için farklı sonuç
    # verebilir. İkisi de kaydedilir ki fark ölçülebilsin.
    ("izmir.search_datasets", {"q": "otobus"}, "Türkçe karaktersiz yazım"),
    # BOŞ SONUÇ vakaları GERÇEKÇİ sorgularla kurulur. "zzzbulunmayan..."
    # gibi bariz sahte terimler hiçbir kullanıcının yazmayacağı şeylerdir ve
    # doğal dil iddiasını çürütür. Bunlar canlıda 0 sonuç döndüğü doğrulanmış,
    # tamamen makul sorulardır.
    (
        "izmir.search_datasets",
        {"q": "elektrikli scooter"},
        "BOŞ SONUÇ -- gerçekçi ama portalda olmayan konu",
    ),
    # -- metadata -----------------------------------------------------------
    (
        "izmir.get_dataset_metadata",
        {"dataset_id": STOPS_DATASET},
        "kompozisyon zincirinin 2. adımı -> resource_id",
    ),
    ("izmir.get_dataset_metadata", {"dataset_id": TAXI_DATASET}, "ikinci zincir, taksi"),
    (
        "izmir.get_dataset_metadata",
        {"dataset_id": "duraga-yaklasan-otobusler"},
        "datastore_active=false olan veri seti (negatif örnek malzemesi)",
    ),
    (
        "izmir.get_dataset_metadata",
        {"dataset_id": "izmir-metro-sefer-saatleri"},
        "BEKLENEN HATA -- 404, makul ama var olmayan slug (HTML gövde!)",
    ),
    # -- tablo sorgusu ------------------------------------------------------
    (
        "izmir.query_resource",
        {"resource_id": STOPS_RESOURCE_ID, "limit": 5},
        "kompozisyon zincirinin 3. adımı",
    ),
    (
        "izmir.query_resource",
        {"resource_id": STOPS_RESOURCE_ID, "q": "KONAK", "limit": 5},
        "tam metin filtresi",
    ),
    (
        "izmir.query_resource",
        {"resource_id": STOPS_RESOURCE_ID, "q": "Bahribaba", "limit": 5},
        "tek durak araması",
    ),
    ("izmir.query_resource", {"resource_id": TAXI_RESOURCE_ID, "limit": 5}, "ikinci tablo"),
    (
        "izmir.query_resource",
        {"resource_id": STOPS_RESOURCE_ID, "q": "Beşiktaş", "limit": 5},
        "BOŞ SONUÇ -- İstanbul semtini İzmir'de aramak (gerçekçi kullanıcı hatası)",
    ),
    (
        "izmir.query_resource",
        {"resource_id": "00000000-0000-0000-0000-000000000000", "limit": 5},
        "BEKLENEN HATA -- geçersiz resource",
    ),
]


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=[CassetteMode.RECORD.value, CassetteMode.RECORD_MISSING.value],
        default=CassetteMode.RECORD_MISSING.value,
        help="record: hepsini yeniden çek. record_missing: yalnızca eksikleri.",
    )
    args = parser.parse_args()

    registry = {tool.tool_id: tool for tool in ckan.TOOLS}
    failures = 0

    with build_http_runtime(
        ckan.adapter,
        cassette_root=CASSETTE_ROOT,
        mode=CassetteMode(args.mode),
        git_sha=_git_sha(),
    ) as runtime:
        for tool_id, arguments, reason in CALLS:
            result = runtime.executor.execute(registry[tool_id], arguments)
            status = result.status_code if result.status_code is not None else "-"
            marker = "ok " if result.succeeded else "HATA"
            if result.outcome.value in {"transport_error", "plan_error"}:
                marker = "KIRIK"
                failures += 1
            print(f"  [{marker:>5}] {status:>4}  {tool_id:<30} {reason}")
            if result.error and marker == "KIRIK":
                print(f"          -> {result.error}")

        print(f"\n{len(runtime.store)} kayıt: {runtime.store.dir}")

    digest = write_manifest(CASSETTE_ROOT, [runtime.store])
    print(f"MANIFEST.json -> {digest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
