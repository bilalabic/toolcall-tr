"""`find_nearby_stops` — dondurulmuş snapshot ve yerel haversine.

Buradaki en önemli testler **conformance** testleridir: yerel implementasyonun
belediyenin kendi CBS servisiyle ne kadar uyuştuğunu ölçerler. "Yerel
hesapladık" demek ile "yerel hesapladık ve N/M sorguda aynı sonucu verdi" demek
arasındaki fark, eleştiriye açık olmakla olmamak arasındaki farktır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import ExecutionClass, StepOutcome
from toolcall_tr.providers.izmir import stops as stops_module
from toolcall_tr.providers.izmir.stops import (
    FIND_NEARBY_STOPS,
    StopTable,
    build_adapter,
    haversine_m,
    load_stop_table,
)

#: Snapshot alındığında doğrulanmış satır sayısı.
EXPECTED_ROW_COUNT = 11783

#: Konak Meydanı civarı -- referans nokta.
KONAK_LAT, KONAK_LON = 38.4192, 27.1287


@pytest.fixture(scope="module")
def table() -> StopTable:
    return load_stop_table()


@pytest.fixture(scope="module")
def executor() -> DerivedLocalExecutor:
    return DerivedLocalExecutor(build_adapter())


@pytest.fixture(scope="module")
def conformance(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "tests" / "fixtures" / "cbs_conformance.json"
    if not path.is_file():
        pytest.skip("conformance fixture yok; scripts/record_cbs_conformance.py çalıştırın")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _run(executor: DerivedLocalExecutor, **arguments: Any) -> Any:
    return executor.execute(FIND_NEARBY_STOPS, arguments)


# ---------------------------------------------------------------------------
# Snapshot bütünlüğü
# ---------------------------------------------------------------------------


def test_snapshot_manifest_ile_tutarli(table: StopTable) -> None:
    """SNAPSHOT.json'daki satır sayısı ile gerçek dosya uyuşmalı."""
    assert len(table) == EXPECTED_ROW_COUNT
    assert table.row_count == EXPECTED_ROW_COUNT
    assert table.content_hash.startswith("sha256:")


def test_snapshot_manifesti_lisans_ve_degisiklikleri_beyan_eder(repo_root: Path) -> None:
    """CC BY 4.0 § 3(a): değişiklik yapıldığı da beyan edilmeli."""
    manifest = json.loads(
        (repo_root / "data" / "snapshots" / "eshot_stops" / "SNAPSHOT.json").read_text("utf-8")
    )
    assert manifest["license"] == "CC-BY-4.0"
    assert manifest["attribution"]
    assert manifest["modifications"]
    assert manifest["source"]["resource_id"]
    assert manifest["retrieved_at"]


def test_koordinatlar_izmir_sinirlarinda(table: StopTable) -> None:
    for stop in table.stops:
        assert 37.5 < stop.latitude < 39.5, f"{stop.stop_id} enlem dışarıda"
        assert 26.0 < stop.longitude < 28.5, f"{stop.stop_id} boylam dışarıda"


def test_durak_kimlikleri_benzersiz_degil_ama_aranabilir(table: StopTable) -> None:
    """Aynı DURAK_ID birden fazla satırda olabilir; arama yine de çalışmalı."""
    assert table.contains(10005)
    assert not table.contains(99999999)


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------


def test_ayni_nokta_sifir_mesafe() -> None:
    assert haversine_m(KONAK_LAT, KONAK_LON, KONAK_LAT, KONAK_LON) == pytest.approx(0.0)


def test_bilinen_mesafe() -> None:
    """1 derece enlem ~111.2 km."""
    assert haversine_m(38.0, 27.0, 39.0, 27.0) == pytest.approx(111_195, rel=0.001)


def test_simetrik() -> None:
    a = haversine_m(38.41, 27.12, 38.43, 27.15)
    b = haversine_m(38.43, 27.15, 38.41, 27.12)
    assert a == pytest.approx(b)


# ---------------------------------------------------------------------------
# Sıralama ve sınırlar -- ground-truth'un doğrulanabilirliği buna bağlı
# ---------------------------------------------------------------------------


def test_mesafeye_gore_artan_sirali(table: StopTable) -> None:
    results = table.nearby(KONAK_LAT, KONAK_LON, radius_m=800, limit=20)
    distances = [r["distance_m"] for r in results]
    assert distances == sorted(distances)


def test_esit_mesafede_durak_id_ile_ayrilir(table: StopTable) -> None:
    """Belirsiz sıralama = doğrulanamayan ground-truth."""
    results = table.nearby(KONAK_LAT, KONAK_LON, radius_m=2000, limit=50)
    pairs = [(r["distance_m"], r["stop_id"]) for r in results]
    assert pairs == sorted(pairs)


def test_siralama_tekrarlanabilir(table: StopTable) -> None:
    a = table.nearby(KONAK_LAT, KONAK_LON, radius_m=1000, limit=15)
    b = table.nearby(KONAK_LAT, KONAK_LON, radius_m=1000, limit=15)
    assert a == b


def test_yaricap_disi_elenir(table: StopTable) -> None:
    radius = 300.0
    results = table.nearby(KONAK_LAT, KONAK_LON, radius_m=radius, limit=50)
    assert results
    assert all(r["distance_m"] <= radius for r in results)


def test_limit_filtre_ve_siralamadan_sonra_uygulanir(table: StopTable) -> None:
    """Önce yarıçap, sonra sıralama, en son limit."""
    full = table.nearby(KONAK_LAT, KONAK_LON, radius_m=1000, limit=50)
    limited = table.nearby(KONAK_LAT, KONAK_LON, radius_m=1000, limit=3)
    assert len(limited) == 3
    assert limited == full[:3]


def test_bos_sonuc_gecerlidir(table: StopTable) -> None:
    """Ege Denizi'nin ortasında durak yok -- bu hata değil, cevaptır."""
    results = table.nearby(38.5, 26.2, radius_m=100, limit=10)
    assert results == []
    assert FIND_NEARBY_STOPS.allow_empty_result


def test_hatlar_listeye_ayrilir(table: StopTable) -> None:
    results = table.nearby(KONAK_LAT, KONAK_LON, radius_m=500, limit=10)
    with_lines = [r for r in results if r["lines"]]
    assert with_lines, "Konak civarında hattı olan durak bulunmalı"
    assert all(isinstance(r["lines"], list) for r in results)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def test_tool_derived_local_isaretli() -> None:
    """Dürüstlük: bu tool canlı API'ye gitmiyor ve bunu taşıyor."""
    assert FIND_NEARBY_STOPS.execution_class is ExecutionClass.DERIVED_LOCAL


def test_executor_cassette_anahtari_uretmez(executor: DerivedLocalExecutor) -> None:
    result = _run(executor, latitude=KONAK_LAT, longitude=KONAK_LON)
    assert result.outcome is StepOutcome.OK
    assert result.cassette_key is None
    assert result.status_code is None  # yerel hesaplamanın HTTP durumu yoktur


def test_executor_gercek_durak_dondurur(executor: DerivedLocalExecutor) -> None:
    result = _run(executor, latitude=KONAK_LAT, longitude=KONAK_LON, radius_m=400, limit=5)
    assert result.response["count"] == len(result.response["results"])
    first = result.response["results"][0]
    assert first["stop_id"] > 0
    assert first["name"]
    assert first["distance_m"] <= 400


def test_executor_varsayilanlari_uygular(executor: DerivedLocalExecutor) -> None:
    result = _run(executor, latitude=KONAK_LAT, longitude=KONAK_LON)
    assert result.arguments["radius_m"] == 500
    assert result.arguments["limit"] == 10


def test_executor_gecersiz_enlemi_reddeder(executor: DerivedLocalExecutor) -> None:
    result = _run(executor, latitude=1000.0, longitude=KONAK_LON)
    assert result.outcome is StepOutcome.PLAN_ERROR
    assert "en fazla 90" in (result.error or "")


def test_executor_zorunlu_parametre_ister(executor: DerivedLocalExecutor) -> None:
    result = _run(executor, latitude=KONAK_LAT)
    assert result.outcome is StepOutcome.PLAN_ERROR
    assert "longitude" in (result.error or "")


def test_string_koordinat_normalize_edilir(executor: DerivedLocalExecutor) -> None:
    a = _run(executor, latitude=KONAK_LAT, longitude=KONAK_LON)
    b = _run(executor, latitude=str(KONAK_LAT), longitude=str(KONAK_LON))
    assert a.response == b.response


# ---------------------------------------------------------------------------
# CONFORMANCE -- canlı CBS servisiyle karşılaştırma
# ---------------------------------------------------------------------------


def test_conformance_ornegi_lisans_isaretli(conformance: dict[str, Any]) -> None:
    """openapi.izmir.bel.tr lisansı belirsiz; bu fixture veri setine girmez."""
    assert conformance["license"] == "UNDETERMINED"
    assert "veri setine dâhil edilmez" in conformance["_notice"]


def test_conformance_ilk_durak_ortak(conformance: dict[str, Any], table: StopTable) -> None:
    """En yakın durak her iki implementasyonda da aynı olmalı.

    Bu, uyumun en katı ölçüsüdür: sıralamanın tepesi.
    """
    samples = conformance["samples"]
    assert samples, "örneklem boş"

    matches = 0
    for sample in samples:
        upstream = sample["upstream"]
        if not upstream:
            continue
        local = table.nearby(sample["query"]["lat"], sample["query"]["lon"], radius_m=5000, limit=1)
        if local and int(upstream[0]["durakId"]) == local[0]["stop_id"]:
            matches += 1

    ratio = matches / len(samples)
    assert ratio >= 0.8, f"ilk durak uyumu düşük: {matches}/{len(samples)}"


def test_conformance_mesafe_yakin(conformance: dict[str, Any], table: StopTable) -> None:
    """Mesafeler yakın olmalı.

    Birebir aynı olmaları beklenmez: belediye servisi projeksiyon düzleminde
    ölçüyor, biz büyük daire (haversine) hesaplıyoruz. İzmir ölçeğinde fark
    birkaç metredir.
    """
    deltas: list[float] = []
    for sample in conformance["samples"]:
        upstream = sample["upstream"]
        if not upstream:
            continue
        local = table.nearby(sample["query"]["lat"], sample["query"]["lon"], radius_m=5000, limit=1)
        if not local:
            continue
        if int(upstream[0]["durakId"]) != local[0]["stop_id"]:
            continue
        deltas.append(abs(float(upstream[0]["mesafe"]) - local[0]["distance_m"]))

    assert deltas, "karşılaştırılabilir örnek yok"
    assert max(deltas) < 25.0, f"mesafe farkı büyük: max {max(deltas):.1f} m"


def test_cbs_yaricap_siniri_uygulamiyor(conformance: dict[str, Any]) -> None:
    """CBS servisi listeyi mesafeye bakmadan doldurur — belgelenmiş bir tuzak.

    Her sorguda 11-15 sonuç döner ve bunları *herhangi bir yarıçap sınırı
    olmadan* doldurur: örneklemde en uzak sonucun medyanı ~62 km, maksimumu
    ~106 km'dir (İzmir il sınırının dışı). Bu kayıtların çoğu, yayımlanan
    ESHOT durak tablosunda **bulunmayan** bir veritabanından gelir.

    `find_nearby_stops` bu davranışı taklit etmez: yarıçap gerçekten uygulanır.
    """
    farthest = sorted(
        max(float(item["mesafe"]) for item in sample["upstream"])
        for sample in conformance["samples"]
        if sample["upstream"]
    )
    assert farthest[len(farthest) // 2] > 10_000, "medyan uzaklık beklenenden küçük"


def test_conformance_recall_calisma_araliginda(
    conformance: dict[str, Any], table: StopTable
) -> None:
    """Tool'un gerçek çalışma aralığında (<= 5 km) uyum ölçülür.

    Uzak alan karşılaştırması anlamsızdır: `find_nearby_stops` 5 km'nin ötesine
    hiç bakmaz (`radius_m` üst sınırı 5000), oysa CBS servisi 100 km'den sonuç
    doldurur. Ölçüm bu yüzden aralıkla sınırlıdır -- eşiği gevşetmek değil,
    doğru şeyi ölçmektir.

    Ölçülen değer `legal/DATA_SOURCES.md`'de kayıtlıdır ve dataset card bunu
    alıntılar.
    """
    max_radius = float(FIND_NEARBY_STOPS.parameter("radius_m").maximum)  # type: ignore[union-attr,arg-type]
    known = {stop.stop_id for stop in table.stops}

    total = 0
    found = 0
    for sample in conformance["samples"]:
        for item in sample["upstream"]:
            if float(item["mesafe"]) > max_radius:
                continue
            total += 1
            if int(item["durakId"]) in known:
                found += 1

    assert total >= 200, f"karşılaştırılabilir örnek az: {total}"
    ratio = found / total
    assert ratio >= 0.95, f"çalışma aralığında recall düşük: {found}/{total} = {ratio:.1%}"


def test_epsg_tuzagi_gercek(conformance: dict[str, Any], table: StopTable) -> None:
    """`inCoordSys=4326` (prefix'siz) sessizce yanlış sonuç döndürür.

    Bu test, `find_nearby_stops`'un neden canlı çağrı değil de yerel hesaplama
    olduğunu belgeler: tuzak gerçektir ve hata vermez, sadece yanlış cevap verir.
    """
    trap = conformance["epsg_trap"]
    response = trap["response"]
    if not response:
        pytest.skip("tuzak yanıtı kaydedilememiş")

    query = trap["query"]
    correct = table.nearby(query["lat"], query["lon"], radius_m=1000, limit=1)
    assert correct, "referans nokta yakınında durak olmalı"

    trap_ids = {int(item["durakId"]) for item in response}
    # Tuzak yanıtı doğru cevabı içermiyor -- ilin bambaşka bir ucundan geliyor.
    assert correct[0]["stop_id"] not in trap_ids

    # Ve gerçekten çok uzakta.
    trap_distance = haversine_m(
        query["lat"], query["lon"], float(response[0]["enlem"]), float(response[0]["boylam"])
    )
    assert trap_distance > 20_000, f"tuzak sonucu {trap_distance:.0f} m uzakta"


# ---------------------------------------------------------------------------
# Snapshot izolasyonu
# ---------------------------------------------------------------------------


def test_bozuk_snapshot_reddedilir(tmp_path: Path) -> None:
    """Satır sayısı manifest ile uyuşmuyorsa sessizce devam edilmez."""
    (tmp_path / "stops.jsonl").write_text(
        json.dumps(
            {
                "DURAK_ID": 1,
                "DURAK_ADI": "Test",
                "ENLEM": 38.4,
                "BOYLAM": 27.1,
                "DURAKTAN_GECEN_HATLAR": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "SNAPSHOT.json").write_text(
        json.dumps({"content_hash": "sha256:abc", "row_count": 999}), encoding="utf-8"
    )
    stops_module.load_stop_table.cache_clear()
    with pytest.raises(ValueError, match="snapshot bozuk"):
        load_stop_table(tmp_path)
    stops_module.load_stop_table.cache_clear()
