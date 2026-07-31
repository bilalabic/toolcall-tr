"""İzmir Açık Veri Portalı (CKAN 2.8.5) sağlayıcısı.

Doğrulanmış gerçekler (2026-07-28, canlı HTTP ile teyit edildi):

* Anonim okuma; API anahtarı yok. Anonim yazma HTTP 403.
* CC BY 4.0; beyan edilmiş rate limit yok.
* 257 veri seti, 694 resource; 434'ü ``datastore_active``.
* **``datastore_search_sql`` bu portalda YOKTUR** -- çağrı
  ``"Action name not known"`` döner. Bu yüzden ``query_resource``
  yalnızca ``datastore_search`` kullanır. (İBB portalında SQL etkindir.)

Sıralama politikası -- iki endpoint kasıtlı olarak **farklı** ele alınır:

``datastore_search`` -> ``sort=_id asc`` pinlenir
    CKAN açık ``sort`` olmadan satır sırasını garanti etmez. ``_id asc`` hem
    deterministik hem de bir tablo için doğal sıradır; kaybedilen bir şey yok.

``package_search`` -> sıralama pinlenmez (CKAN varsayılanı: Solr relevance)
    Bu karar bir kez ``sort=metadata_modified desc`` olarak denendi ve
    **geri alındı**: pinleme relevance sıralamasını yok ediyor ve "otobüs"
    aramasının ilk sonucu bir güneş enerjisi santrali veri seti oluyordu.
    Böyle bir sonuç üzerine kurulan observation-grounded cevap saçmalar.

    Determinizm zaten cassette replay ile sağlanır: aynı kayıt her zaman aynı
    sırayı döndürür. Pinlemenin çözdüğü tek şey *yeniden kayıtta* sıranın
    kayması ki bu **değer drift'idir**, yapısal drift değil -- drift job'ı bu
    ikisini ``type_skeleton`` üzerinden zaten ayırır.

Sıralama modele parametre olarak sunulmaz: ground-truth'u kararsızlaştırmasına
izin vermenin bir faydası yok.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding

__all__ = ["BASE_URL", "DATASTORE_SORT", "TOOLS", "adapter", "normalize_ckan"]

BASE_URL = "https://acikveri.bizizmir.com"
PROVIDER = "izmir_ckan"
NAMESPACE = "izmir"

#: Bkz. modül docstring'i. `package_search` için karşılığı **kasıtlı olarak
#: yoktur**: relevance sıralaması korunur.
DATASTORE_SORT = "_id asc"

LICENSE = "CC-BY-4.0"
ATTRIBUTION = (
    "Atıf 4.0 Uluslararası (CC BY 4.0) kapsamında lisanslanan kamu sektörü "
    "bilgilerini içerir. Kaynak: İzmir Büyükşehir Belediyesi Açık Veri Portalı."
)

_SOURCE = ToolSource(
    schema_type="ckan",
    schema_version="ckan-2.8.5/2026-07",
    upstream_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def normalize_ckan(payload: Any) -> Any:
    """CKAN zarfını normalize eder.

    Tek değişiklik: ``help`` alanı atılır. Her yanıtta tekrarlanan, uzun ve
    bilgi taşımayan bir dokümantasyon URL'idir; cassette diff'lerini ve
    observation'ları gereksiz yere şişirir. Bu, ``LICENSE-DATA`` § 2'de beyan
    edilen değişikliklerden biridir.
    """
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if key != "help"}
    return payload


def _action_url(action: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/3/action/{action}"


def _build_package_search(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    # `sort` gönderilmez: CKAN varsayılanı olan Solr relevance sıralaması
    # korunur. Gerekçe modül docstring'inde.
    params: dict[str, Any] = {
        "q": arguments["q"],
        "rows": arguments.get("rows", 5),
        "start": arguments.get("start", 0),
    }
    return httpx.Request("GET", _action_url("package_search", base_url), params=params)


def _build_package_show(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        _action_url("package_show", base_url),
        params={"id": arguments["dataset_id"]},
    )


def _build_datastore_search(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params: dict[str, Any] = {
        "resource_id": arguments["resource_id"],
        "limit": arguments.get("limit", 10),
        "offset": arguments.get("offset", 0),
        "sort": DATASTORE_SORT,
    }
    query = arguments.get("q")
    if query is not None and query != "":
        params["q"] = query
    return httpx.Request("GET", _action_url("datastore_search", base_url), params=params)


# ---------------------------------------------------------------------------
# Tool tanımları
# ---------------------------------------------------------------------------

SEARCH_DATASETS = ToolSpec(
    tool_id="izmir.search_datasets",
    provider=PROVIDER,
    name="search_datasets",
    description_tr=(
        "İzmir Büyükşehir Belediyesi açık veri portalında anahtar kelimeyle "
        "veri seti arar. Sonuçlar en son güncellenenden başlayarak sıralanır."
    ),
    parameters=(
        ParamSpec(
            name="q",
            type="string",
            description_tr="Aranacak anahtar kelime veya ifade. Örnek: 'otobüs durak'.",
            required=True,
            semantic_type="search_query",
            min_length=1,
        ),
        ParamSpec(
            name="rows",
            type="integer",
            description_tr="Döndürülecek en fazla veri seti sayısı.",
            minimum=1,
            maximum=100,
            has_default=True,
            default=5,
        ),
        ParamSpec(
            name="start",
            type="integer",
            description_tr="Sayfalama için atlanacak kayıt sayısı.",
            minimum=0,
            has_default=True,
            default=0,
        ),
    ),
    outputs=(
        OutputField(
            path="result.count",
            type="integer",
            description_tr="Sorguyla eşleşen toplam veri seti sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="result.results[*].id",
            type="string",
            description_tr="Veri setinin benzersiz kimliği.",
            semantic_type="package_id",
        ),
        OutputField(
            path="result.results[*].name",
            type="string",
            description_tr="Veri setinin URL'de kullanılan kısa adı.",
            semantic_type="package_id",
        ),
        OutputField(
            path="result.results[*].title",
            type="string",
            description_tr="Veri setinin okunabilir başlığı.",
        ),
        OutputField(
            path="result.results[*].notes",
            type="string",
            description_tr="Veri setinin açıklaması.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_DATASET_METADATA = ToolSpec(
    tool_id="izmir.get_dataset_metadata",
    provider=PROVIDER,
    name="get_dataset_metadata",
    description_tr=(
        "Bir veri setinin ayrıntılı bilgilerini ve içindeki kaynak (resource) "
        "listesini getirir. Kaynak kimlikleri tablo sorgulamak için kullanılır."
    ),
    parameters=(
        ParamSpec(
            name="dataset_id",
            type="string",
            description_tr="Veri setinin kimliği veya kısa adı.",
            required=True,
            semantic_type="package_id",
            min_length=1,
        ),
    ),
    outputs=(
        OutputField(
            path="result.id",
            type="string",
            description_tr="Veri setinin benzersiz kimliği.",
            semantic_type="package_id",
        ),
        OutputField(
            path="result.title",
            type="string",
            description_tr="Veri setinin okunabilir başlığı.",
        ),
        OutputField(
            path="result.notes",
            type="string",
            description_tr="Veri setinin açıklaması.",
        ),
        OutputField(
            path="result.license_title",
            type="string",
            description_tr="Veri setinin lisansı.",
        ),
        OutputField(
            path="result.num_resources",
            type="integer",
            description_tr="Veri setindeki kaynak sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="result.resources[*].id",
            type="string",
            description_tr="Kaynağın (tablo/dosya) benzersiz kimliği.",
            semantic_type="resource_id",
        ),
        OutputField(
            path="result.resources[*].name",
            type="string",
            description_tr="Kaynağın adı.",
        ),
        OutputField(
            path="result.resources[*].format",
            type="string",
            description_tr="Kaynağın biçimi (CSV, JSON, API ...).",
        ),
        OutputField(
            path="result.resources[*].datastore_active",
            type="boolean",
            description_tr="Kaynağın tablo olarak sorgulanabilir olup olmadığı.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

QUERY_RESOURCE = ToolSpec(
    tool_id="izmir.query_resource",
    provider=PROVIDER,
    name="query_resource",
    description_tr=(
        "Açık veri portalındaki bir tabloyu satır bazında sorgular. "
        "İsteğe bağlı anahtar kelimeyle tam metin araması yapılabilir."
    ),
    parameters=(
        ParamSpec(
            name="resource_id",
            type="string",
            description_tr="Sorgulanacak kaynağın (tablonun) kimliği.",
            required=True,
            semantic_type="resource_id",
            min_length=1,
        ),
        ParamSpec(
            name="q",
            type="string",
            description_tr="Tabloda aranacak anahtar kelime. Boş bırakılırsa tüm satırlar.",
            semantic_type="search_query",
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="Döndürülecek en fazla satır sayısı.",
            minimum=1,
            maximum=100,
            has_default=True,
            default=10,
        ),
        ParamSpec(
            name="offset",
            type="integer",
            description_tr="Sayfalama için atlanacak satır sayısı.",
            minimum=0,
            has_default=True,
            default=0,
        ),
    ),
    outputs=(
        OutputField(
            path="result.total",
            type="integer",
            description_tr="Sorguyla eşleşen toplam satır sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="result.records[*]",
            type="object",
            description_tr="Tablo satırı.",
            semantic_type="table_record",
        ),
        OutputField(
            path="result.fields[*].id",
            type="string",
            description_tr="Tablodaki sütun adı.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_DATASETS, GET_DATASET_METADATA, QUERY_RESOURCE)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(SEARCH_DATASETS, _build_package_search, normalize_ckan),
        ToolBinding(GET_DATASET_METADATA, _build_package_show, normalize_ckan),
        ToolBinding(QUERY_RESOURCE, _build_datastore_search, normalize_ckan),
    ),
)
