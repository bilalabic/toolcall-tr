"""Cassette katmanı — yeniden üretilebilirliğin temeli.

En kritik test ``test_replay_ag_olmadan_calisir``: bir yapılandırma regresyonu
"doğrulanmış" bir derlemeyi sessizce canlı-getirme derlemesine çevirebilmemeli.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from toolcall_tr.execution.cassette import (
    SENSITIVE_HEADERS,
    CassetteLimitError,
    CassetteMissError,
    CassetteMode,
    CassetteStore,
    CassetteTransport,
    NoNetworkTransport,
    read_manifest_hash,
    request_key,
    write_manifest,
)

CKAN = "https://acikveri.bizizmir.com/api/3/action/package_search"


def _request(url: str = CKAN, method: str = "GET", **kwargs: Any) -> httpx.Request:
    return httpx.Request(method, url, **kwargs)


def _json_handler(body: Any, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def store(tmp_path: Path) -> CassetteStore:
    return CassetteStore(
        tmp_path / "cassettes",
        "izmir",
        license="CC-BY-4.0",
        attribution="İzmir Büyükşehir Belediyesi Açık Veri Portalı, CC BY 4.0",
    )


# ---------------------------------------------------------------------------
# İstek anahtarı
# ---------------------------------------------------------------------------


def test_query_sirasi_anahtari_etkilemez() -> None:
    """`?a=1&b=2` ile `?b=2&a=1` aynı kaydı bulmalı."""
    assert request_key(_request(f"{CKAN}?rows=3&q=otobüs")) == request_key(
        _request(f"{CKAN}?q=otobüs&rows=3")
    )


def test_farkli_deger_farkli_anahtar() -> None:
    assert request_key(_request(f"{CKAN}?q=otobüs")) != request_key(_request(f"{CKAN}?q=metro"))


def test_farkli_yol_farkli_anahtar() -> None:
    a = _request("https://acikveri.bizizmir.com/api/3/action/package_show")
    assert request_key(a) != request_key(_request())


def test_method_anahtara_girer() -> None:
    assert request_key(_request(method="GET")) != request_key(_request(method="POST"))


def test_hassas_basliklar_anahtara_girmez() -> None:
    """Aynı istek, farklı token -- aynı kaydı bulmalı."""
    a = _request(headers={"Authorization": "Bearer aaa"})
    b = _request(headers={"Authorization": "Bearer bbb"})
    assert request_key(a) == request_key(b) == request_key(_request())


def test_govde_json_olarak_normalize_edilir() -> None:
    """Anahtar sırası farklı ama semantik aynı iki gövde eşleşmeli."""
    a = _request(method="POST", json={"a": 1, "b": 2})
    b = _request(method="POST", json={"b": 2, "a": 1})
    assert request_key(a) == request_key(b)


# ---------------------------------------------------------------------------
# Depolama
# ---------------------------------------------------------------------------


def test_ayni_govde_tek_blob_olarak_saklanir(store: CassetteStore) -> None:
    """Sayısız boş `[]` yanıtı diskte tek kez yer kaplamalı."""
    payload = {"status": 200, "headers": {}, "body_encoding": "json", "body": []}
    first = store.write_blob(payload)
    second = store.write_blob(dict(payload))
    assert first == second
    assert len(list((store.dir / "blobs").rglob("*.json"))) == 1


def test_kayit_oncesi_govde_guvenli_alt_kumeye_indirgenir(store: CassetteStore) -> None:
    transport = CassetteTransport(
        store,
        CassetteMode.RECORD,
        inner=_json_handler({"id": 1, "body": "serbest metin"}),
    )
    request = _request()
    key = transport.key_for(request)
    transport.set_response_sanitizer(key, lambda payload: {"id": payload["id"]})
    with httpx.Client(transport=transport) as client:
        response = client.send(request)
    assert response.json() == {"id": 1}
    payload = transport.payloads_for([key])
    assert payload[f"izmir:{key}"] == {"id": 1}


def test_blob_icerigi_hash_ile_dogrulanir(store: CassetteStore) -> None:
    blob_id = store.write_blob({"body": {"ok": True}})
    path = store.blob_path(blob_id)
    path.write_text('{"body":{"ok":false}}\n', encoding="utf-8")

    with pytest.raises(CassetteMissError, match="bütünlük hatası"):
        store.read_blob(blob_id)


def test_blob_yolu_shardlanir(store: CassetteStore) -> None:
    """Windows'ta MAX_PATH için sharding zorunlu."""
    blob_id = "sha256:" + "ab" + "c" * 62
    path = store.blob_path(blob_id)
    assert path.parent.name == "ab"
    assert path.name.startswith("c")


def test_index_anahtara_gore_sirali_yazilir(tmp_path: Path) -> None:
    """Deterministik ve PR'da okunabilir kalmalı."""
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        for q in ("zeta", "alpha", "mu"):
            client.get(CKAN, params={"q": q})
    store.save()

    keys = [json.loads(line)["key"] for line in store.index_path.read_text("utf-8").splitlines()]
    assert keys == sorted(keys)


def test_index_hash_kararli(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN, params={"q": "otobüs"})
    store.save()
    before = store.index_hash()

    reloaded = CassetteStore(tmp_path, "izmir")
    assert reloaded.index_hash() == before


def test_atif_her_blobun_icinde(tmp_path: Path) -> None:
    """Tek bir dosya depodan çıkarıldığında dahi CC BY yükümlülüğünü taşımalı."""
    store = CassetteStore(
        tmp_path, "izmir", license="CC-BY-4.0", attribution="İzmir Büyükşehir Belediyesi"
    )
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN)
    store.save()

    blob = json.loads(next((store.dir / "blobs").rglob("*.json")).read_text("utf-8"))
    attribution = blob["attribution"]
    assert attribution["license"] == "CC-BY-4.0"
    assert "İzmir" in attribution["attribution"]
    # CC BY 4.0 §3(a): değişiklik yapıldığı da beyan edilmeli.
    assert "normalize" in attribution["modified"]


def test_hassas_basliklar_diske_yazilmaz(tmp_path: Path) -> None:
    """Kimlik bilgisi execution altyapısına aittir, veriye değil."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True},
            headers={"Set-Cookie": "session=gizli", "Content-Type": "application/json"},
            request=request,
        )

    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=httpx.MockTransport(handler))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN, headers={"Authorization": "Bearer gizli-token"})
    store.save()

    on_disk = "\n".join(p.read_text("utf-8") for p in store.dir.rglob("*") if p.is_file()).lower()
    assert "gizli" not in on_disk
    assert "bearer" not in on_disk
    for header in SENSITIVE_HEADERS:
        assert header not in on_disk


# ---------------------------------------------------------------------------
# Modlar
# ---------------------------------------------------------------------------


def test_replay_kaydi_oynatir(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    with httpx.Client(
        transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"count": 257}))
    ) as client:
        client.get(CKAN)
    store.save()

    # Ağ olmadan, ayrı bir depo örneğinden.
    replay_store = CassetteStore(tmp_path, "izmir")
    with httpx.Client(transport=CassetteTransport(replay_store, CassetteMode.REPLAY)) as client:
        response = client.get(CKAN)
    assert response.status_code == 200
    assert response.json() == {"count": 257}


def test_replay_kayit_yoksa_hata_verir(store: CassetteStore) -> None:
    with (
        httpx.Client(transport=CassetteTransport(store, CassetteMode.REPLAY)) as client,
        pytest.raises(CassetteMissError, match="Cassette bulunamadı"),
    ):
        client.get(CKAN)


def test_record_missing_eksigi_kaydeder(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(
        store, CassetteMode.RECORD_MISSING, inner=_json_handler({"count": 1})
    )
    with httpx.Client(transport=transport) as client:
        client.get(CKAN)
        client.get(CKAN)  # ikincisi kayıttan gelmeli
    assert len(store) == 1


def test_hata_durumu_da_kaydedilir(tmp_path: Path) -> None:
    """Beklenen hata ground-truth'un kendisidir; 404 de kaydedilmeli."""
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(
        store, CassetteMode.RECORD, inner=_json_handler({"error": "Not Found"}, status=404)
    )
    with httpx.Client(transport=transport) as client:
        client.get(CKAN)
    store.save()

    replay = CassetteStore(tmp_path, "izmir")
    with httpx.Client(transport=CassetteTransport(replay, CassetteMode.REPLAY)) as client:
        assert client.get(CKAN).status_code == 404


def test_bos_dizi_korunur(tmp_path: Path) -> None:
    """`[]` ESHOT'ta geçerli bir sonuçtur ("yaklaşan otobüs yok"), hata değil."""
    store = CassetteStore(tmp_path, "izmir_realtime")
    with httpx.Client(
        transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler([]))
    ) as client:
        client.get(CKAN)
    store.save()

    replay = CassetteStore(tmp_path, "izmir_realtime")
    with httpx.Client(transport=CassetteTransport(replay, CassetteMode.REPLAY)) as client:
        response = client.get(CKAN)
    assert response.json() == []
    assert response.status_code == 200


def test_turkce_karakterler_korunur(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    body = {"DURAK_ADI": "Bahribaba", "ilce": "Konak", "not": "İzmir Büyükşehir — ğüşiöç"}
    with httpx.Client(
        transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler(body))
    ) as client:
        client.get(CKAN)
    store.save()

    replay = CassetteStore(tmp_path, "izmir")
    with httpx.Client(transport=CassetteTransport(replay, CassetteMode.REPLAY)) as client:
        assert client.get(CKAN).json() == body


# ---------------------------------------------------------------------------
# Sıralı yanıtlar -- %5'lik durum, %95'e maliyeti yok
# ---------------------------------------------------------------------------


def test_sequenced_tool_sirali_yanit_dondurur(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir_realtime")
    key = request_key(_request(CKAN))

    responses = [[{"OtobusId": 1}], [{"OtobusId": 2}]]
    index = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal index
        payload = responses[index]
        index += 1
        return httpx.Response(200, json=payload, request=request)

    record = CassetteTransport(
        store,
        CassetteMode.RECORD,
        inner=httpx.MockTransport(handler),
        sequenced_keys=frozenset({key}),
    )
    with httpx.Client(transport=record) as client:
        client.get(CKAN)
        client.get(CKAN)
    store.save()

    replay_store = CassetteStore(tmp_path, "izmir_realtime")
    transport = CassetteTransport(replay_store, CassetteMode.REPLAY)
    with httpx.Client(transport=transport) as client:
        assert client.get(CKAN).json() == [{"OtobusId": 1}]
        assert client.get(CKAN).json() == [{"OtobusId": 2}]
        # İmleç son yanıtta sabitlenir, taşmaz.
        assert client.get(CKAN).json() == [{"OtobusId": 2}]

        transport.reset_cursors()
        assert client.get(CKAN).json() == [{"OtobusId": 1}]


def test_varsayilan_tool_tek_yanit_tutar(tmp_path: Path) -> None:
    """`sequenced` işaretlenmemiş tool'da yeniden kayıt üzerine yazar."""
    store = CassetteStore(tmp_path, "izmir")
    for payload in ({"v": 1}, {"v": 2}):
        with httpx.Client(
            transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler(payload))
        ) as client:
            client.get(CKAN)
    store.save()

    entry = store.get(request_key(_request(CKAN)))
    assert entry is not None
    assert len(entry.blobs) == 1


# ---------------------------------------------------------------------------
# Ağ yasağı
# ---------------------------------------------------------------------------


def test_replay_ag_olmadan_calisir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CI ağa erişememeli -- sadece "replay'e default'lamamalı".

    Soket açma girişimi patlarsa bile pipeline tamamlanmalı. Bu test olmadan
    bir yapılandırma regresyonu fark edilmeden aylarca canlı veri çekebilir.
    """
    store = CassetteStore(tmp_path, "izmir")
    with httpx.Client(
        transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"count": 3}))
    ) as client:
        client.get(CKAN)
    store.save()

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay sırasında ağ erişimi denendi")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    replay = CassetteStore(tmp_path, "izmir")
    with httpx.Client(transport=CassetteTransport(replay, CassetteMode.REPLAY)) as client:
        assert client.get(CKAN).json() == {"count": 3}


def test_varsayilan_ic_tasima_agi_reddeder(store: CassetteStore) -> None:
    """`inner` verilmezse ağ kapalıdır -- güvenli varsayılan."""
    transport = CassetteTransport(store, CassetteMode.RECORD_MISSING)
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(CassetteMissError, match="Ağ erişimi kapalı"),
    ):
        client.get(CKAN)


def test_no_network_transport_her_istegi_reddeder() -> None:
    with (
        httpx.Client(transport=NoNetworkTransport()) as client,
        pytest.raises(CassetteMissError),
    ):
        client.get(CKAN)


# ---------------------------------------------------------------------------
# Lisans sınırı
# ---------------------------------------------------------------------------


def test_kayit_ust_siniri_zorlanir(tmp_path: Path) -> None:
    """Lisansı belirsiz kaynakta toplu kayıt riskini sınırlar."""
    store = CassetteStore(tmp_path, "izmir_realtime", license="UNDETERMINED", max_entries=2)
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN, params={"n": "1"})
        client.get(CKAN, params={"n": "2"})
        with pytest.raises(CassetteLimitError, match="üst sınırı"):
            client.get(CKAN, params={"n": "3"})


def test_mevcut_kaydin_uzerine_yazmak_siniri_asmaz(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir_realtime", max_entries=1)
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN)
        client.get(CKAN)  # aynı anahtar -- yeni kayıt değil
    assert len(store) == 1


# ---------------------------------------------------------------------------
# Manifest, yetim tespiti
# ---------------------------------------------------------------------------


def test_manifest_yazilir_ve_okunur(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir", license="CC-BY-4.0")
    realtime = CassetteStore(tmp_path, "izmir_realtime", license="UNDETERMINED")
    digest = write_manifest(tmp_path, [store, realtime])

    assert read_manifest_hash(tmp_path) == digest

    manifest = json.loads((tmp_path / "MANIFEST.json").read_text("utf-8"))
    # Lisans durumu manifest'te görünür kalmalı.
    assert manifest["providers"]["izmir"]["license"] == "CC-BY-4.0"
    assert manifest["providers"]["izmir_realtime"]["license"] == "UNDETERMINED"


def test_manifest_icerik_degisince_degisir(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    before = write_manifest(tmp_path, [store])

    with httpx.Client(
        transport=CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"a": 1}))
    ) as client:
        client.get(CKAN)
    store.save()

    assert write_manifest(tmp_path, [store]) != before


def test_yetim_kayit_tespiti(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN, params={"q": "kullanilan"})
        client.get(CKAN, params={"q": "yetim"})

    used = {request_key(_request(f"{CKAN}?q=kullanilan"))}
    orphans = store.orphans(used)
    assert len(orphans) == 1

    assert store.prune(used) == orphans
    assert len(store) == 1


def test_kullanilan_anahtarlar_izlenir(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path, "izmir")
    transport = CassetteTransport(store, CassetteMode.RECORD, inner=_json_handler({"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(CKAN)
    assert transport.used_keys == {request_key(_request(CKAN))}
