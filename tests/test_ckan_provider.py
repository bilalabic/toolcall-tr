"""İzmir CKAN sağlayıcısı — depoya işlenmiş **gerçek** cassette'lere karşı.

Bu testler ağa çıkmaz ama uydurma veri de kullanmaz: `data/cassettes/izmir/`
altındaki kayıtlar canlı portaldan alınmıştır. Böylece "execution-verified"
iddiası test seviyesinde de doğrulanır.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from toolcall_tr.execution.cassette import CassetteMode
from toolcall_tr.execution.environment import HTTPProviderRuntime, build_http_runtime
from toolcall_tr.models import ExecutionClass, SideEffect, StepOutcome
from toolcall_tr.providers.izmir import ckan
from toolcall_tr.registry.registry import build_registry
from toolcall_tr.schema import normalize_arguments, validate_arguments

STOPS_RESOURCE_ID = "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
STOPS_DATASET = "eshot-otobus-duraklari"

#: Kayıt anındaki doğrulanmış satır sayısı. Değişirse yapısal değil değer
#: drift'idir, ama zincirin hâlâ doğru tabloya bağlandığını kanıtlar.
STOPS_ROW_COUNT = 11783


@pytest.fixture
def runtime(repo_root: Path) -> Iterator[HTTPProviderRuntime]:
    with build_http_runtime(
        ckan.adapter,
        cassette_root=repo_root / "data" / "cassettes",
        mode=CassetteMode.REPLAY,
    ) as rt:
        yield rt


def _call(runtime: HTTPProviderRuntime, tool_id: str, **arguments: Any) -> Any:
    tool = next(t for t in ckan.TOOLS if t.tool_id == tool_id)
    return runtime.executor.execute(tool, arguments)


# ---------------------------------------------------------------------------
# İstek kurucuları
# ---------------------------------------------------------------------------


def test_datastore_search_sort_pinlenir() -> None:
    """Açık sort olmadan CKAN satır sırasını garanti etmez."""
    binding = ckan.adapter.binding("izmir.query_resource")
    assert binding is not None
    request = binding.build_request({"resource_id": "abc", "limit": 10, "offset": 0}, ckan.BASE_URL)
    assert request.url.params["sort"] == "_id asc"


def test_package_search_sort_pinlenmez() -> None:
    """Pinleme relevance sıralamasını yok ediyordu; kasıtlı olarak geri alındı."""
    binding = ckan.adapter.binding("izmir.search_datasets")
    assert binding is not None
    request = binding.build_request({"q": "otobüs", "rows": 5, "start": 0}, ckan.BASE_URL)
    assert "sort" not in request.url.params


def test_bos_q_datastore_sorgusuna_eklenmez() -> None:
    """Boş string bir filtre değildir; gönderilirse CKAN hiçbir satır döndürmez."""
    binding = ckan.adapter.binding("izmir.query_resource")
    assert binding is not None
    request = binding.build_request(
        {"resource_id": "abc", "q": "", "limit": 10, "offset": 0}, ckan.BASE_URL
    )
    assert "q" not in request.url.params


def test_normalize_help_alanini_atar() -> None:
    """Her yanıtta tekrarlanan uzun dokümantasyon URL'i; observation'ı şişirir."""
    payload = {"help": "https://...uzun...", "success": True, "result": {"count": 1}}
    assert ckan.normalize_ckan(payload) == {"success": True, "result": {"count": 1}}


# ---------------------------------------------------------------------------
# Registry ve türetilmiş kompozisyon grafiği
# ---------------------------------------------------------------------------


def test_registry_kurulur() -> None:
    registry = build_registry(ckan.TOOLS)
    assert len(registry) == 3
    assert registry.tool_ids() == (
        "izmir.get_dataset_metadata",
        "izmir.query_resource",
        "izmir.search_datasets",
    )


def test_yinelenen_tool_reddedilir() -> None:
    with pytest.raises(ValueError, match="yinelenen tool_id"):
        build_registry(ckan.TOOLS, ckan.TOOLS)


def test_bilinmeyen_tool_gurultulu_patlar() -> None:
    """Bilinmeyen tool oranı sıfır toleranslı; sessizce None dönmek yanlış."""
    registry = build_registry(ckan.TOOLS)
    with pytest.raises(KeyError, match="bulunmayan tool"):
        registry.require("izmir.yok_boyle_bir_tool")


def test_kompozisyon_grafigi_semantik_tipten_turetilir() -> None:
    """Elle yazılmış function graph yok; graph semantic_type'tan çıkar."""
    registry = build_registry(ckan.TOOLS)
    edges = registry.composition_edges()
    pairs = {(e.source_tool, e.target_tool, e.target_parameter) for e in edges}

    # search_datasets -> package_id -> get_dataset_metadata
    assert ("izmir.search_datasets", "izmir.get_dataset_metadata", "dataset_id") in pairs
    # get_dataset_metadata -> resource_id -> query_resource
    assert ("izmir.get_dataset_metadata", "izmir.query_resource", "resource_id") in pairs


def test_kompozisyon_grafiginde_kendine_kenar_yok() -> None:
    registry = build_registry(ckan.TOOLS)
    assert all(e.source_tool != e.target_tool for e in registry.composition_edges())


def test_registry_hash_kararli() -> None:
    assert build_registry(ckan.TOOLS).content_hash() == build_registry(ckan.TOOLS).content_hash()


def test_tum_ckan_toollari_salt_okunur() -> None:
    """Yazma işlemi canlı ortamda çalıştırılamaz."""
    for tool in ckan.TOOLS:
        assert tool.side_effect is SideEffect.READ
        assert tool.execution_class is ExecutionClass.LIVE_RECORDED
        assert tool.source.license == "CC-BY-4.0"
        assert tool.source.attribution


# ---------------------------------------------------------------------------
# Argüman normalizasyonu -- cassette anahtarının kararlılığı buna bağlı
# ---------------------------------------------------------------------------


def test_string_sayi_int_e_cevrilir() -> None:
    """`{"rows": "5"}` ile `{"rows": 5}` aynı isteği ve aynı cassette'i üretmeli."""
    tool = next(t for t in ckan.TOOLS if t.name == "search_datasets")
    assert normalize_arguments(tool, {"q": "otobüs", "rows": "5"})["rows"] == 5


def test_varsayilanlar_doldurulur() -> None:
    """Atlanmış opsiyonel ile açıkça verilmiş varsayılan aynı isteği üretmeli."""
    tool = next(t for t in ckan.TOOLS if t.name == "search_datasets")
    assert normalize_arguments(tool, {"q": "otobüs"}) == {"q": "otobüs", "rows": 5, "start": 0}


def test_normalize_edilmis_iki_cagri_ayni_cassette_i_bulur(runtime: HTTPProviderRuntime) -> None:
    a = _call(runtime, "izmir.search_datasets", q="otobüs", rows=3)
    b = _call(runtime, "izmir.search_datasets", q="otobüs", rows="3")
    assert a.cassette_key == b.cassette_key
    assert a.succeeded and b.succeeded


def test_bilinmeyen_parametre_yakalanir() -> None:
    tool = next(t for t in ckan.TOOLS if t.name == "search_datasets")
    errors = validate_arguments(tool, {"q": "x", "uydurma": 1})
    assert any("şemada olmayan parametre" in e for e in errors)


def test_zorunlu_parametre_eksikligi_yakalanir() -> None:
    tool = next(t for t in ckan.TOOLS if t.name == "query_resource")
    errors = validate_arguments(tool, {"limit": 5})
    assert any("zorunlu parametre eksik" in e and "resource_id" in e for e in errors)


def test_sinir_disi_deger_yakalanir() -> None:
    tool = next(t for t in ckan.TOOLS if t.name == "search_datasets")
    errors = validate_arguments(tool, {"q": "x", "rows": 500})
    assert any("en fazla 100" in e for e in errors)


def test_sema_hatasi_plan_hatasidir(runtime: HTTPProviderRuntime) -> None:
    """Şema hatası gürültülü patlar ve asla veriye dönüşmez."""
    result = _call(runtime, "izmir.search_datasets", q="x", uydurma_parametre=1)
    assert result.outcome is StepOutcome.PLAN_ERROR
    assert "şemada olmayan parametre" in (result.error or "")


# ---------------------------------------------------------------------------
# Gerçek cassette'lere karşı çalıştırma
# ---------------------------------------------------------------------------


def test_arama_gercek_sonuc_dondurur(runtime: HTTPProviderRuntime) -> None:
    result = _call(runtime, "izmir.search_datasets", q="otobüs durak")
    assert result.succeeded
    assert result.status_code == 200
    names = [d["name"] for d in result.response["result"]["results"]]
    # Relevance sıralaması korunduğu için en alakalı sonuç başta olmalı.
    assert names[0] == STOPS_DATASET


def test_uc_adimli_kompozisyon_zinciri(runtime: HTTPProviderRuntime) -> None:
    """arama -> package_id -> metadata -> resource_id -> tablo.

    Zincirin her halkası gerçek veriyle bağlanır; hiçbir kimlik elle
    yazılmamıştır.
    """
    search = _call(runtime, "izmir.search_datasets", q="otobüs durak")
    package_name = search.response["result"]["results"][0]["name"]

    metadata = _call(runtime, "izmir.get_dataset_metadata", dataset_id=package_name)
    assert metadata.succeeded
    resources = metadata.response["result"]["resources"]
    queryable = [r for r in resources if r["datastore_active"]]
    assert queryable, "zincir sorgulanabilir bir kaynağa ulaşmalı"

    table = _call(runtime, "izmir.query_resource", resource_id=queryable[0]["id"], limit=5)
    assert table.succeeded
    assert table.response["result"]["total"] == STOPS_ROW_COUNT
    columns = {f["id"] for f in table.response["result"]["fields"]}
    assert {"DURAK_ID", "DURAK_ADI", "ENLEM", "BOYLAM"} <= columns


def test_durak_koordinatlari_wgs84(runtime: HTTPProviderRuntime) -> None:
    """CKAN datastore'daki koordinatlar temiz -- ESHOT realtime'ın aksine."""
    result = _call(runtime, "izmir.query_resource", resource_id=STOPS_RESOURCE_ID, limit=5)
    record = result.response["result"]["records"][0]
    assert isinstance(record["ENLEM"], float)
    assert 38.0 < record["ENLEM"] < 39.0  # İzmir enlem aralığı
    assert 26.0 < record["BOYLAM"] < 28.0


def test_bos_sonuc_hata_degildir(runtime: HTTPProviderRuntime) -> None:
    """`allow_empty_result` olmadan execution validator en ilginç vakayı reddeder."""
    result = _call(runtime, "izmir.search_datasets", q="elektrikli scooter")
    assert result.succeeded
    assert result.response["result"]["count"] == 0
    assert result.response["result"]["results"] == []


def test_bos_tablo_filtresi_hata_degildir(runtime: HTTPProviderRuntime) -> None:
    result = _call(
        runtime,
        "izmir.query_resource",
        resource_id=STOPS_RESOURCE_ID,
        q="Beşiktaş",
        limit=5,
    )
    assert result.succeeded
    assert result.response["result"]["records"] == []


def test_404_altyapi_hatasi_degil_domain_hatasidir(runtime: HTTPProviderRuntime) -> None:
    """İzmir CKAN'ı 404'te JSON değil HTML döndürür.

    Bunu altyapı hatası saymak "beklenen hata" senaryolarını tamamen
    imkânsız kılardı: episode iptal edilir ve örnek asla üretilmezdi.
    """
    result = _call(runtime, "izmir.get_dataset_metadata", dataset_id="izmir-metro-sefer-saatleri")
    assert result.status_code == 404
    assert result.outcome is StepOutcome.UNEXPECTED_ERROR
    assert result.outcome is not StepOutcome.TRANSPORT_ERROR
    assert "text/html" in (result.error or "")


def test_gecersiz_resource_da_domain_hatasi(runtime: HTTPProviderRuntime) -> None:
    result = _call(
        runtime, "izmir.query_resource", resource_id="00000000-0000-0000-0000-000000000000", limit=5
    )
    assert result.status_code == 404
    assert result.outcome is StepOutcome.UNEXPECTED_ERROR


def test_turkce_karakter_sonucu_degistirir(runtime: HTTPProviderRuntime) -> None:
    """Solr analyzer'ı ü/u'yu eşitlemiyor -- Türkçe'ye özgü gerçek bir hata modu.

    Kullanıcının Türkçe karakter kullanıp kullanmaması sonucu değiştirir.
    Bu, veri setinde kasıtlı olarak temsil edilen bir olgudur.
    """
    with_diacritic = _call(runtime, "izmir.search_datasets", q="otobüs")
    without = _call(runtime, "izmir.search_datasets", q="otobus")
    assert with_diacritic.response["result"]["count"] == 17
    assert without.response["result"]["count"] == 9


def test_datastore_active_false_olan_kaynak_vardir(runtime: HTTPProviderRuntime) -> None:
    """Zinciri yanlış veri setinden kurmak sessizce sorgulanamaz kimlik üretir."""
    result = _call(runtime, "izmir.get_dataset_metadata", dataset_id="duraga-yaklasan-otobusler")
    assert result.succeeded
    resources = result.response["result"]["resources"]
    assert resources
    assert all(not r["datastore_active"] for r in resources)


def test_cassette_anahtari_raporlanir(runtime: HTTPProviderRuntime) -> None:
    """Her adım hangi kaydı tükettiğini bildirmeli -- yetim tespiti buna dayanır."""
    result = _call(runtime, "izmir.search_datasets", q="otobüs")
    assert result.cassette_key is not None
    assert result.cassette_key.startswith("sha256:")
    assert result.cassette_key in runtime.store


def test_lisans_her_kayitta_isaretli(runtime: HTTPProviderRuntime) -> None:
    assert runtime.store.license == "CC-BY-4.0"
    entry = next(iter(runtime.store.keys()))
    assert runtime.store.get(entry) is not None
    assert runtime.store.get(entry).metadata["license"] == "CC-BY-4.0"  # type: ignore[union-attr]


def test_replay_ag_olmadan_calisir(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tüm sağlayıcı, soket açılamazken bile çalışmalı."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay sırasında ağ erişimi denendi")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    with build_http_runtime(
        ckan.adapter,
        cassette_root=repo_root / "data" / "cassettes",
        mode=CassetteMode.REPLAY,
    ) as rt:
        assert _call(rt, "izmir.search_datasets", q="otobüs").succeeded
