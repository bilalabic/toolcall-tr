"""ESHOT gerçek zamanlı sağlayıcısı ve normalizasyonu.

Kaynak yanıtındaki üç tuzağın tek noktada düzeltildiğini doğrular:
koordinat isimlerinin ters olması, virgüllü ondalık ayraç ve boş sonucun
geçerli bir cevap olması.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from toolcall_tr.execution.cassette import CassetteMode
from toolcall_tr.execution.environment import HTTPProviderRuntime, build_http_runtime
from toolcall_tr.models import ExecutionClass, StepOutcome
from toolcall_tr.providers.base import ToolExecutionError
from toolcall_tr.providers.izmir import eshot
from toolcall_tr.providers.izmir.eshot import (
    GET_APPROACHING_BUSES,
    normalize_approaching_buses,
    parse_tr_coordinate,
)

#: Kayıt anında araç bulunan / boş dönen duraklar.
STOP_WITH_BUSES = 10102
STOP_EMPTY = 15532

#: Ham kaynak biçimi. Dikkat: KoorX enlem, KoorY boylamdır.
RAW_BUS = {
    "KalanDurakSayisi": 14,
    "HattinYonu": 1,
    "KoorY": "27,175345",
    "BisikletAparatliMi": False,
    "KoorX": "38,382445",
    "EngelliMi": True,
    "HatNumarasi": 304,
    "HatAdi": "TINAZTEPE-KONAK",
    "OtobusId": 11246,
}


@pytest.fixture
def runtime(repo_root: Path) -> Iterator[HTTPProviderRuntime]:
    with build_http_runtime(
        eshot.adapter,
        cassette_root=repo_root / "data" / "cassettes",
        mode=CassetteMode.REPLAY,
    ) as rt:
        yield rt


def _call(runtime: HTTPProviderRuntime, stop_id: int) -> Any:
    return runtime.executor.execute(GET_APPROACHING_BUSES, {"stop_id": stop_id})


# ---------------------------------------------------------------------------
# Koordinat ayrıştırma
# ---------------------------------------------------------------------------


def test_virgullu_ondalik_cozulur() -> None:
    """`float("27,175345")` patlar; virgülü silmek 27 milyon üretir."""
    assert parse_tr_coordinate("27,175345", field="test") == pytest.approx(27.175345)


def test_zaten_sayi_olan_deger_gecer() -> None:
    assert parse_tr_coordinate(38.4192, field="test") == pytest.approx(38.4192)


def test_bozuk_koordinat_gurultulu_patlar() -> None:
    with pytest.raises(ToolExecutionError, match="ayrıştırılamadı"):
        parse_tr_coordinate("kuzeyde bir yerde", field="test")


def test_bool_koordinat_reddedilir() -> None:
    with pytest.raises(ToolExecutionError, match="beklenmeyen koordinat tipi"):
        parse_tr_coordinate(True, field="test")


# ---------------------------------------------------------------------------
# Normalizasyon -- KoorX/KoorY takası
# ---------------------------------------------------------------------------


def test_koorx_enlem_koory_boylamdir() -> None:
    """İsimler kaynakta terstir; bu takas sessizce İzmir'i denize taşır."""
    result = normalize_approaching_buses([RAW_BUS])
    bus = result["results"][0]
    assert bus["latitude"] == pytest.approx(38.382445)  # KoorX'ten
    assert bus["longitude"] == pytest.approx(27.175345)  # KoorY'den


def test_takas_geri_alinirsa_gurultulu_patlar() -> None:
    """Kaynak bir gün takası düzeltirse sessizce yanlış veri üretmemeliyiz."""
    swapped = {**RAW_BUS, "KoorX": "27,175345", "KoorY": "38,382445"}
    with pytest.raises(ToolExecutionError, match="İzmir aralığı dışında"):
        normalize_approaching_buses([swapped])


def test_alanlar_okunabilir_adlara_cevrilir() -> None:
    bus = normalize_approaching_buses([RAW_BUS])["results"][0]
    assert bus["bus_id"] == 11246
    assert bus["line_number"] == 304
    assert bus["line_name"] == "TINAZTEPE-KONAK"
    assert bus["stops_remaining"] == 14
    assert bus["wheelchair_accessible"] is True
    assert bus["bike_rack"] is False


def test_bos_liste_gecerli_sonuctur() -> None:
    """ "Yaklaşan otobüs yok" bir cevaptır, hata değil."""
    assert normalize_approaching_buses([]) == {"count": 0, "results": []}
    assert GET_APPROACHING_BUSES.allow_empty_result


def test_siralama_deterministik() -> None:
    """Kaynak sıralama garantisi vermiyor; ground-truth için sabitlenir."""
    far = {**RAW_BUS, "OtobusId": 1, "KalanDurakSayisi": 9}
    near = {**RAW_BUS, "OtobusId": 2, "KalanDurakSayisi": 2}
    result = normalize_approaching_buses([far, near])
    assert [b["stops_remaining"] for b in result["results"]] == [2, 9]


def test_beklenmeyen_govde_reddedilir() -> None:
    with pytest.raises(ToolExecutionError, match="beklenen liste"):
        normalize_approaching_buses({"hata": "mesaj"})


# ---------------------------------------------------------------------------
# Gerçek cassette'lere karşı
# ---------------------------------------------------------------------------


def test_gercek_durakta_arac_bilgisi(runtime: HTTPProviderRuntime) -> None:
    result = _call(runtime, STOP_WITH_BUSES)
    assert result.outcome is StepOutcome.OK
    assert result.response["count"] > 0

    bus = result.response["results"][0]
    # Normalize edilmiş koordinatlar gerçekten İzmir'de olmalı.
    assert 37.5 < bus["latitude"] < 39.5
    assert 26.0 < bus["longitude"] < 28.5
    assert bus["line_number"] > 0
    assert isinstance(bus["stops_remaining"], int)


def test_gercek_bos_sonuc(runtime: HTTPProviderRuntime) -> None:
    """En ilginç vaka: doğru cevap "hiçbir şey yok"."""
    result = _call(runtime, STOP_EMPTY)
    assert result.outcome is StepOutcome.OK
    assert result.response == {"count": 0, "results": []}


def test_sonuclar_kalan_duraga_gore_sirali(runtime: HTTPProviderRuntime) -> None:
    result = _call(runtime, STOP_WITH_BUSES)
    remaining = [b["stops_remaining"] for b in result.response["results"]]
    assert remaining == sorted(remaining)


def test_ham_govde_cassettede_normalize_govde_sonucta(runtime: HTTPProviderRuntime) -> None:
    """İkisi kasıtlı olarak farklıdır."""
    result = _call(runtime, STOP_WITH_BUSES)
    assert result.cassette_key is not None

    entry = runtime.store.get(result.cassette_key)
    assert entry is not None
    raw = runtime.store.read_blob(entry.blobs[0])["body"]

    # Ham gövde kaynağın biçiminde: liste, KoorX/KoorY, virgüllü string.
    assert isinstance(raw, list)
    assert "KoorX" in raw[0]
    assert isinstance(raw[0]["KoorX"], str)
    assert "," in raw[0]["KoorX"]

    # Tool sonucu normalize: nesne, latitude/longitude, float.
    assert isinstance(result.response, dict)
    assert isinstance(result.response["results"][0]["latitude"], float)


def test_gecersiz_stop_id_reddedilir(runtime: HTTPProviderRuntime) -> None:
    result = runtime.executor.execute(GET_APPROACHING_BUSES, {"stop_id": 0})
    assert result.outcome is StepOutcome.PLAN_ERROR
    assert "en az 1" in (result.error or "")


def test_zorunlu_parametre_eksikse_plan_hatasi(runtime: HTTPProviderRuntime) -> None:
    result = runtime.executor.execute(GET_APPROACHING_BUSES, {})
    assert result.outcome is StepOutcome.PLAN_ERROR
    assert "stop_id" in (result.error or "")


# ---------------------------------------------------------------------------
# Lisans disiplini
# ---------------------------------------------------------------------------


def test_lisans_belirsiz_olarak_isaretli() -> None:
    """`openapi.izmir.bel.tr` için beyan edilmiş lisans yok (LICENSE-DATA § 3)."""
    assert eshot.LICENSE == "UNDETERMINED"
    assert eshot.adapter.license == "UNDETERMINED"
    assert GET_APPROACHING_BUSES.source.license == "UNDETERMINED"


def test_ayri_cassette_namespace(runtime: HTTPProviderRuntime) -> None:
    """CC BY 4.0 kayıtlarıyla karışmamalı."""
    assert eshot.adapter.cassette_namespace == "izmir_realtime"
    assert runtime.store.namespace == "izmir_realtime"
    assert runtime.store.dir.name == "izmir_realtime"


def test_kayit_sayisi_sinirli(repo_root: Path) -> None:
    """Lisans belirsizken toplu yeniden dağıtım riski sınırlanır."""
    assert eshot.MAX_CASSETTES <= 100
    with build_http_runtime(
        eshot.adapter,
        cassette_root=repo_root / "data" / "cassettes",
        mode=CassetteMode.REPLAY,
        max_entries=eshot.MAX_CASSETTES,
    ) as rt:
        assert len(rt.store) <= eshot.MAX_CASSETTES


def test_sequenced_isaretli() -> None:
    """Aynı durak aynı episode'da iki kez sorulursa yanıt meşru olarak değişir."""
    assert GET_APPROACHING_BUSES.sequenced
    assert GET_APPROACHING_BUSES.tool_id in eshot.adapter.sequenced_tools


def test_live_recorded_olarak_isaretli() -> None:
    assert GET_APPROACHING_BUSES.execution_class is ExecutionClass.LIVE_RECORDED
