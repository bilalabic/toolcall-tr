"""ESHOT / İztek gerçek zamanlı servisleri — `get_approaching_buses`.

> **LİSANS UYARISI:** `openapi.izmir.bel.tr`, CC BY 4.0 doğrulanmış
> `acikveri.bizizmir.com` ile **ayrı bir host**tur ve beyan edilmiş bir lisansı
> yoktur. Bkz. `LICENSE-DATA` § 3. Bu sağlayıcının cassette'leri ayrı bir
> namespace'te tutulur, sayıca sınırlıdır ve manifest'te `UNDETERMINED`
> işaretlenir. **Yayın öncesi çözülmesi gereken açık bir maddedir.**

Kaynak yanıtındaki üç tuzak burada, **tek noktada** düzeltilir:

1. **`KoorX` enlemdir, `KoorY` boylamdır** — isimler terstir. X/Y adlandırması
   normalde (boylam, enlem) beklendiği için bu, sessizce İzmir'i Somali
   açıklarına taşıyan türden bir hatadır.
2. Koordinatlar **virgüllü ondalık ayraçlı string**'dir (``"27,175345"``).
3. Boş dizi ``[]`` **geçerli bir cevaptır** ("yaklaşan otobüs yok"), hata değil.

Ham gövde cassette'e, normalize gövde tool sonucuna yazılır; ikisi kasıtlı
olarak farklıdır.
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
    "GET_APPROACHING_BUSES",
    "TOOLS",
    "adapter",
    "normalize_approaching_buses",
    "parse_tr_coordinate",
]

BASE_URL = "https://openapi.izmir.bel.tr"
PROVIDER = "izmir_realtime"
NAMESPACE = "izmir_realtime"

#: Lisans belirsiz olduğu için kayıt sayısı kasıtlı olarak sınırlıdır.
MAX_CASSETTES = 60

#: İzmir ili kabaca bu aralıktadır. Aralık dışı bir koordinat, kaynağın
#: `KoorX`/`KoorY` takasını düzelttiği (ya da başka bir şeyin bozulduğu)
#: anlamına gelir ve sessizce yanlış veri üretmektense gürültülü patlamalıdır.
IZMIR_LAT_RANGE = (37.5, 39.5)
IZMIR_LON_RANGE = (26.0, 28.5)

LICENSE = "UNDETERMINED"
ATTRIBUTION = "İzmir Büyükşehir Belediyesi / ESHOT"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="iztek/2026-07",
    operation_id="duragayaklasanotobusler",
    upstream_url=f"{BASE_URL}/api/iztek/duragayaklasanotobusler",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def parse_tr_coordinate(raw: Any, *, field: str) -> float:
    """``"27,175345"`` -> ``27.175345``.

    Kaynak koordinatları Türkçe yerel ayarla, virgüllü ondalık ayraçla
    string olarak döndürür. ``float("27,175345")`` patlar; sessizce
    ``float(raw.replace(",", ""))`` demek ise 27 milyon üretir.
    """
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return float(raw)
    if not isinstance(raw, str):
        raise ToolExecutionError(f"{field}: beklenmeyen koordinat tipi {type(raw).__name__}")
    text = raw.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ToolExecutionError(f"{field}: koordinat ayrıştırılamadı ({raw!r})") from exc


def normalize_approaching_buses(payload: Any) -> dict[str, Any]:
    """Ham İztek yanıtını tool sonucuna çevirir.

    Koordinat takası ve ondalık ayraç dönüşümü **yalnızca burada** yapılır.
    """
    if payload is None:
        return {"count": 0, "results": []}
    if not isinstance(payload, list):
        raise ToolExecutionError(f"beklenen liste, gelen {type(payload).__name__}")

    results: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ToolExecutionError(f"beklenen nesne, gelen {type(item).__name__}")

        # DİKKAT: KoorX enlem, KoorY boylamdır. İsimler kaynakta terstir.
        latitude = parse_tr_coordinate(item.get("KoorX"), field="KoorX(enlem)")
        longitude = parse_tr_coordinate(item.get("KoorY"), field="KoorY(boylam)")

        if not (IZMIR_LAT_RANGE[0] <= latitude <= IZMIR_LAT_RANGE[1]):
            raise ToolExecutionError(
                f"enlem İzmir aralığı dışında ({latitude}). Kaynak KoorX/KoorY "
                "takasını düzeltmiş olabilir -- normalize.py gözden geçirilmeli."
            )
        if not (IZMIR_LON_RANGE[0] <= longitude <= IZMIR_LON_RANGE[1]):
            raise ToolExecutionError(
                f"boylam İzmir aralığı dışında ({longitude}). Kaynak KoorX/KoorY "
                "takasını düzeltmiş olabilir -- normalize.py gözden geçirilmeli."
            )

        results.append(
            {
                "bus_id": int(item["OtobusId"]),
                "line_number": int(item["HatNumarasi"]),
                "line_name": str(item.get("HatAdi") or "").strip(),
                "direction": int(item["HattinYonu"]),
                "stops_remaining": int(item["KalanDurakSayisi"]),
                "latitude": latitude,
                "longitude": longitude,
                "wheelchair_accessible": bool(item.get("EngelliMi", False)),
                "bike_rack": bool(item.get("BisikletAparatliMi", False)),
            }
        )

    # Deterministik sıra: kaynak sıralama garantisi vermiyor.
    results.sort(key=lambda r: (r["stops_remaining"], r["line_number"], r["bus_id"]))
    return {"count": len(results), "results": results}


def _build_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    stop_id = arguments["stop_id"]
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/api/iztek/duragayaklasanotobusler/{stop_id}",
    )


GET_APPROACHING_BUSES = ToolSpec(
    tool_id="izmir.get_approaching_buses",
    provider=PROVIDER,
    name="get_approaching_buses",
    description_tr=(
        "Belirtilen İzmir otobüs durağına yaklaşan araçları, kaç durak kaldığı "
        "bilgisiyle birlikte listeler. Yaklaşan araç yoksa boş liste döner."
    ),
    parameters=(
        ParamSpec(
            name="stop_id",
            type="integer",
            description_tr="İzmir otobüs durağı numarası. Örnek: 10030.",
            required=True,
            semantic_type="durak_id",
            minimum=1,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Yaklaşan araç sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].bus_id",
            type="integer",
            description_tr="Aracın kimliği.",
        ),
        OutputField(
            path="results[*].line_number",
            type="integer",
            description_tr="Hat numarası.",
            semantic_type="hat_no",
        ),
        OutputField(
            path="results[*].line_name",
            type="string",
            description_tr="Hattın adı (güzergâh).",
        ),
        OutputField(
            path="results[*].stops_remaining",
            type="integer",
            description_tr="Araca kaç durak kaldığı.",
        ),
        OutputField(
            path="results[*].wheelchair_accessible",
            type="boolean",
            description_tr="Aracın engelli erişimine uygun olup olmadığı.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    # "Yaklaşan otobüs yok" geçerli bir cevaptır. Bu bayrak olmadan execution
    # validator en ilginç vakayı hata sayıp reddeder.
    allow_empty_result=True,
    # Aynı durak aynı episode içinde iki kez sorulursa yanıt meşru olarak
    # değişebilir; cassette sıralı yanıt tutar.
    sequenced=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (GET_APPROACHING_BUSES,)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    sequenced_tools=frozenset({GET_APPROACHING_BUSES.tool_id}),
    bindings=(ToolBinding(GET_APPROACHING_BUSES, _build_request, normalize_approaching_buses),),
)
