"""MediaWiki Action API; makale metni ve extract olmadan yalnızca metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://tr.wikipedia.org"
PROVIDER = "wikimedia_metadata"
NAMESPACE = "wikimedia_metadata"
LICENSE = "WIKIMEDIA-METADATA-ONLY"
ATTRIBUTION = "Türkçe Vikipedi katkıcıları; yalnızca sayfa metadata alanları"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="mediawiki-action-api/2026-07",
    upstream_url=f"{BASE_URL}/w/api.php",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _common() -> dict[str, Any]:
    return {"action": "query", "format": "json", "formatversion": 2}


def _search_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    params = {
        **_common(),
        "list": "search",
        "srsearch": arguments["query"],
        "srnamespace": 0,
        "srlimit": arguments.get("limit", 5),
        # `snippet` bilerek yok: makale metnini yeniden dağıtmayız.
        "srprop": "size|wordcount|timestamp",
    }
    return httpx.Request("GET", f"{base_url.rstrip('/')}/w/api.php", params=params)


def normalize_search(payload: Any) -> dict[str, Any]:
    try:
        search = payload["query"]["search"]
        total = payload["query"]["searchinfo"]["totalhits"]
    except (KeyError, TypeError) as exc:
        raise ToolExecutionError("MediaWiki search yanıtı geçersiz") from exc
    results = [
        {
            "page_id": int(row["pageid"]),
            "title": str(row["title"]),
            "namespace": int(row["ns"]),
            "size_bytes": int(row.get("size") or 0),
            "word_count": int(row.get("wordcount") or 0),
            "timestamp": str(row.get("timestamp") or ""),
            "canonical_url": f"{BASE_URL}/wiki/{quote(str(row['title']).replace(' ', '_'))}",
        }
        for row in search
        if isinstance(row, dict)
    ]
    return {"total_hits": int(total), "count": len(results), "results": results}


def _metadata_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/w/api.php",
        params={
            **_common(),
            "prop": "info",
            "pageids": int(arguments["page_id"]),
            "inprop": "url",
        },
    )


def _single_page(payload: Any, label: str) -> dict[str, Any]:
    try:
        page = payload["query"]["pages"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ToolExecutionError(f"MediaWiki {label} yanıtı geçersiz") from exc
    if not isinstance(page, dict) or page.get("missing"):
        raise ToolExecutionError(f"MediaWiki sayfası bulunamadı: {label}")
    return page


def normalize_metadata(payload: Any) -> dict[str, Any]:
    page = _single_page(payload, "info")
    return {
        "page_id": int(page["pageid"]),
        "title": str(page["title"]),
        "namespace": int(page["ns"]),
        "length_bytes": int(page.get("length") or 0),
        "last_revision_id": int(page.get("lastrevid") or 0),
        "touched": str(page.get("touched") or ""),
        "canonical_url": str(page.get("canonicalurl") or page.get("fullurl") or ""),
    }


def _categories_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/w/api.php",
        params={
            **_common(),
            "prop": "categories",
            "pageids": int(arguments["page_id"]),
            "clshow": "!hidden",
            "cllimit": arguments.get("limit", 20),
        },
    )


def normalize_categories(payload: Any) -> dict[str, Any]:
    page = _single_page(payload, "categories")
    categories = [
        {"title": str(row["title"])}
        for row in page.get("categories", [])
        if isinstance(row, dict) and row.get("title")
    ]
    categories.sort(key=lambda row: row["title"])
    return {
        "page_id": int(page["pageid"]),
        "title": str(page["title"]),
        "count": len(categories),
        "categories": categories,
    }


SEARCH_PAGES = ToolSpec(
    tool_id="knowledge.search_pages",
    provider=PROVIDER,
    name="search_pages",
    description_tr="Türkçe Vikipedi'de metin alıntısı olmadan sayfa metadata'sı arar.",
    parameters=(
        ParamSpec(name="query", type="string", description_tr="Arama sorgusu.", required=True, min_length=2),
        ParamSpec(name="limit", type="integer", description_tr="En fazla sonuç.", minimum=1, maximum=10, has_default=True, default=5),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Dönen sayfa sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].page_id", type="integer", description_tr="MediaWiki sayfa kimliği.", semantic_type="page_id"),
        OutputField(path="results[*].title", type="string", description_tr="Sayfa başlığı.", semantic_type="page_title"),
        OutputField(path="results[*].canonical_url", type="string", description_tr="Kalıcı sayfa URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_PAGE_METADATA = ToolSpec(
    tool_id="knowledge.get_page_metadata",
    provider=PROVIDER,
    name="get_page_metadata",
    description_tr="Bir Türkçe Vikipedi sayfasının kimlik, URL, boyut ve sürüm metadata'sını getirir.",
    parameters=(
        ParamSpec(name="page_id", type="integer", description_tr="MediaWiki sayfa kimliği.", required=True, minimum=1, semantic_type="page_id"),
    ),
    outputs=(
        OutputField(path="page_id", type="integer", description_tr="MediaWiki sayfa kimliği.", semantic_type="page_id"),
        OutputField(path="title", type="string", description_tr="Sayfa başlığı.", semantic_type="page_title"),
        OutputField(path="last_revision_id", type="integer", description_tr="Son sürüm kimliği."),
        OutputField(path="canonical_url", type="string", description_tr="Kalıcı sayfa URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

LIST_PAGE_CATEGORIES = ToolSpec(
    tool_id="knowledge.list_page_categories",
    provider=PROVIDER,
    name="list_page_categories",
    description_tr="Bir Türkçe Vikipedi sayfasının gizli olmayan kategori başlıklarını listeler.",
    parameters=(
        ParamSpec(name="page_id", type="integer", description_tr="MediaWiki sayfa kimliği.", required=True, minimum=1, semantic_type="page_id"),
        ParamSpec(name="limit", type="integer", description_tr="En fazla kategori.", minimum=1, maximum=50, has_default=True, default=20),
    ),
    outputs=(
        OutputField(path="page_id", type="integer", description_tr="MediaWiki sayfa kimliği.", semantic_type="page_id"),
        OutputField(path="count", type="integer", description_tr="Kategori sayısı.", semantic_type="result_count"),
        OutputField(path="categories[*].title", type="string", description_tr="Kategori başlığı."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_PAGES, GET_PAGE_METADATA, LIST_PAGE_CATEGORIES)
adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(SEARCH_PAGES, _search_request, normalize_search),
        ToolBinding(GET_PAGE_METADATA, _metadata_request, normalize_metadata),
        ToolBinding(LIST_PAGE_CATEGORIES, _categories_request, normalize_categories),
    ),
)
