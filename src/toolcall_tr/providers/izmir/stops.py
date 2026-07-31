"""`find_nearby_stops` — dondurulmuş durak tablosu üzerinde yerel haversine.

**Neden canlı çağrı değil?** Belediyenin `cbs/noktayayakinduraklar` endpoint'i
``inCoordSys=4326`` (prefix'siz) verildiğinde CRS'i **sessizce yok sayar**,
girdiyi projeksiyon metresi kabul eder ve ilin bambaşka bir ucundan sonuç
döner -- hata vermeden. Ground-truth'u böyle bir tuzağın üstüne kurmak
istemedik.

Buna karşılık dondurulmuş tablo:

* CC BY 4.0 ve koordinatları zaten temiz WGS84,
* beş yıl sonra da yeniden üretilebilir (endpoint kaybolsa bile),
* CRS tuzağını tamamen ortadan kaldırır.

Bu bir zayıflık değil, gerekçeli bir tasarım kararıdır -- ve iddia
`tests/test_stops.py::test_conformance_*` ile ölçülür: yerel implementasyon
belediye servisiyle örneklem üzerinde karşılaştırılır ve uyum oranı dataset
card'a yazılır.

`execution_class="derived_local"` her tool ve her örnekte taşınır; "tüm
cevaplar canlı API'den geldi" iddiası **asla** yapılmaz.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import LocalProviderAdapter, LocalToolBinding

__all__ = [
    "EARTH_RADIUS_M",
    "FIND_NEARBY_STOPS",
    "Stop",
    "StopTable",
    "build_adapter",
    "default_snapshot_dir",
    "haversine_m",
    "load_stop_table",
]

PROVIDER = "izmir_snapshot"

#: IUGG ortalama Dünya yarıçapı (metre).
EARTH_RADIUS_M = 6_371_008.8

#: Mesafe sıralamadan **önce** bu hassasiyete yuvarlanır. Aksi hâlde float
#: gürültüsü eşit uzaklıktaki durakları platformdan platforma farklı sıralar
#: ve ground-truth doğrulanamaz hâle gelir.
DISTANCE_PRECISION = 1

LICENSE = "CC-BY-4.0"
ATTRIBUTION = (
    "İzmir Büyükşehir Belediyesi Açık Veri Portalı, CC BY 4.0. "
    "Dondurulmuş ve değiştirilmiş alt küme."
)

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="eshot_stops/2026-07",
    upstream_url="https://acikveri.bizizmir.com",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def default_snapshot_dir() -> Path:
    """Depo içindeki varsayılan snapshot dizini."""
    return Path(__file__).resolve().parents[4] / "data" / "snapshots" / "eshot_stops"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """İki WGS84 noktası arasındaki büyük daire mesafesi (metre)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True)
class Stop:
    stop_id: int
    name: str
    latitude: float
    longitude: float
    lines: str

    def line_list(self) -> list[str]:
        return [part.strip() for part in self.lines.split(",") if part.strip()]


class StopTable:
    """Dondurulmuş durak tablosu ve üzerindeki sorgular."""

    def __init__(self, stops: Sequence[Stop], *, content_hash: str, row_count: int) -> None:
        self.stops = tuple(stops)
        self.content_hash = content_hash
        self.row_count = row_count

    def __len__(self) -> int:
        return len(self.stops)

    def get(self, stop_id: int) -> Stop | None:
        return next((s for s in self.stops if s.stop_id == stop_id), None)

    def contains(self, stop_id: int) -> bool:
        """Grounding validator için: bu `durak_id` gerçekten var mı?"""
        return self.get(stop_id) is not None

    def nearby(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_m: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Yarıçap içindeki durakları mesafeye göre sıralı döner.

        Sıralama **toplam**dır: eşit mesafedeki iki durak `DURAK_ID` ile
        ayrılır. Belirsiz sıralama, doğrulanamayan bir ground-truth demektir.

        `limit` filtreleme ve sıralamadan **sonra** uygulanır.
        """
        found: list[tuple[float, int, Stop]] = []
        for stop in self.stops:
            distance = haversine_m(latitude, longitude, stop.latitude, stop.longitude)
            rounded = round(distance, DISTANCE_PRECISION)
            if rounded <= radius_m:
                found.append((rounded, stop.stop_id, stop))

        found.sort(key=lambda item: (item[0], item[1]))
        return [
            {
                "stop_id": stop.stop_id,
                "name": stop.name,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
                "distance_m": rounded,
                "lines": stop.line_list(),
            }
            for rounded, _, stop in found[:limit]
        ]


@lru_cache(maxsize=4)
def load_stop_table(snapshot_dir: Path | None = None) -> StopTable:
    """Snapshot'ı diskten yükler.

    Sonuç önbelleklenir: 11.783 satır her çağrıda yeniden ayrıştırılmaz. Anahtar
    dizin yolu olduğu için testler kendi snapshot'larını izole edebilir.
    """
    directory = snapshot_dir or default_snapshot_dir()
    manifest = json.loads((directory / "SNAPSHOT.json").read_text(encoding="utf-8"))
    stops = [
        Stop(
            stop_id=int(row["DURAK_ID"]),
            name=str(row["DURAK_ADI"]),
            latitude=float(row["ENLEM"]),
            longitude=float(row["BOYLAM"]),
            lines=str(row["DURAKTAN_GECEN_HATLAR"]),
        )
        for row in (
            json.loads(line)
            for line in (directory / "stops.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        )
    ]
    table = StopTable(
        stops,
        content_hash=str(manifest["content_hash"]),
        row_count=int(manifest["row_count"]),
    )
    if len(table) != table.row_count:
        raise ValueError(
            f"snapshot bozuk: SNAPSHOT.json {table.row_count} satır diyor, "
            f"stops.jsonl {len(table)} satır içeriyor"
        )
    return table


FIND_NEARBY_STOPS = ToolSpec(
    tool_id="izmir.find_nearby_stops",
    provider=PROVIDER,
    name="find_nearby_stops",
    description_tr=(
        "Verilen koordinata en yakın otobüs duraklarını mesafeye göre sıralı "
        "olarak listeler. Mesafe kuş uçuşu (metre) hesaplanır."
    ),
    parameters=(
        ParamSpec(
            name="latitude",
            type="number",
            description_tr="Aranacak noktanın enlemi (WGS84). Örnek: 38.4192.",
            required=True,
            semantic_type="latitude",
            minimum=-90.0,
            maximum=90.0,
        ),
        ParamSpec(
            name="longitude",
            type="number",
            description_tr="Aranacak noktanın boylamı (WGS84). Örnek: 27.1287.",
            required=True,
            semantic_type="longitude",
            minimum=-180.0,
            maximum=180.0,
        ),
        ParamSpec(
            name="radius_m",
            type="integer",
            description_tr="Arama yarıçapı (metre).",
            minimum=50,
            maximum=5000,
            has_default=True,
            default=500,
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Döndürülecek en fazla durak sayısı.",
            minimum=1,
            maximum=50,
            has_default=True,
            default=10,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Bulunan durak sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].stop_id",
            type="integer",
            description_tr="Durak numarası.",
            semantic_type="durak_id",
        ),
        OutputField(
            path="results[*].name",
            type="string",
            description_tr="Durak adı.",
        ),
        OutputField(
            path="results[*].distance_m",
            type="number",
            description_tr="Noktaya kuş uçuşu mesafe (metre).",
        ),
        OutputField(
            path="results[*].lines",
            type="array",
            description_tr="Duraktan geçen hat numaraları.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    # Yarıçap içinde durak bulunmaması geçerli bir cevaptır ("yakınında durak yok").
    allow_empty_result=True,
    source=_SOURCE,
)


def build_adapter(snapshot_dir: Path | None = None) -> LocalProviderAdapter:
    """Yerel sağlayıcıyı kurar.

    Fabrika fonksiyonu kasıtlıdır: modül seviyesinde sabit bir adaptör, import
    anında 11.783 satır yüklerdi ve testlerin kendi snapshot'larını
    kullanmasını imkânsız kılardı.
    """
    table = load_stop_table(snapshot_dir)

    def run_find_nearby_stops(arguments: Mapping[str, Any]) -> dict[str, Any]:
        results = table.nearby(
            float(arguments["latitude"]),
            float(arguments["longitude"]),
            radius_m=float(arguments.get("radius_m", 500)),
            limit=int(arguments.get("limit", 10)),
        )
        return {"count": len(results), "results": results}

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes={"eshot_stops": table.content_hash},
        bindings=(LocalToolBinding(FIND_NEARBY_STOPS, run_find_nearby_stops),),
    )


TOOLS: tuple[ToolSpec, ...] = (FIND_NEARBY_STOPS,)
