"""Crossref REST API; özet/tam metin olmadan bibliyografik metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

__all__ = [
    "GET_WORK_METADATA",
    "SEARCH_WORKS",
    "TOOLS",
    "adapter",
    "normalize_get_work",
    "normalize_search",
]

BASE_URL = "https://api.crossref.org"
PROVIDER = "crossref"
NAMESPACE = "crossref"
LICENSE = "CROSSREF-METADATA"
ATTRIBUTION = "Crossref open scholarly metadata; abstracts and full text excluded"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="crossref-rest/2026-07",
    upstream_url=f"{BASE_URL}/works",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

_SELECT = (
    "DOI,title,type,URL,published,container-title,publisher,"
    "references-count,is-referenced-by-count"
)


def _date_parts(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    numbers = [int(item) for item in parts[0][:3]]
    if not numbers:
        return None
    if len(numbers) == 1:
        return f"{numbers[0]:04d}"
    if len(numbers) == 2:
        return f"{numbers[0]:04d}-{numbers[1]:02d}"
    return f"{numbers[0]:04d}-{numbers[1]:02d}-{numbers[2]:02d}"


def _first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return ""


def _safe_work(row: Mapping[str, Any]) -> dict[str, Any]:
    licenses = row.get("license")
    license_urls = []
    if isinstance(licenses, list):
        license_urls = sorted(
            {
                str(item["URL"])
                for item in licenses
                if isinstance(item, Mapping) and item.get("URL")
            }
        )
    return {
        "container_title": _first_text(row.get("container-title")),
        "doi": str(row.get("DOI") or ""),
        "is_referenced_by_count": int(row.get("is-referenced-by-count") or 0),
        "license_urls": license_urls,
        "published": _date_parts(row.get("published")),
        "publisher": str(row.get("publisher") or ""),
        "reference_count": int(
            row.get("references-count") or row.get("reference-count") or 0
        ),
        "title": _first_text(row.get("title")),
        "type": str(row.get("type") or ""),
        "url": str(row.get("URL") or ""),
    }


def _search_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    filters = []
    if arguments.get("from_year") is not None:
        filters.append(f"from-pub-date:{int(arguments['from_year'])}-01-01")
    if arguments.get("work_type"):
        filters.append(f"type:{arguments['work_type']}")
    sort_by = str(arguments.get("sort_by", "relevance"))
    params: dict[str, Any] = {
        "query.bibliographic": arguments["query"],
        "rows": arguments.get("limit", 5),
        "select": _SELECT,
    }
    if filters:
        params["filter"] = ",".join(filters)
    if sort_by == "published":
        params.update({"sort": "published", "order": "desc"})
    return httpx.Request("GET", f"{base_url.rstrip('/')}/works", params=params)


def normalize_search(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("message"), Mapping):
        raise ToolExecutionError("Crossref work arama yanıtı geçersiz")
    message = payload["message"]
    items = message.get("items")
    if not isinstance(items, list):
        raise ToolExecutionError("Crossref work listesi eksik")
    results = [_safe_work(row) for row in items if isinstance(row, Mapping)]
    return {
        "count": len(results),
        "results": results,
        "total_results": int(message.get("total-results") or 0),
    }


def _get_work_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    doi = quote(str(arguments["doi"]), safe="")
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/works/{doi}",
    )


def normalize_get_work(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("message"), Mapping):
        raise ToolExecutionError("Crossref work metadata yanıtı geçersiz")
    return _safe_work(payload["message"])


def sanitize_search_cassette(payload: Any) -> dict[str, Any]:
    normalized = normalize_search(payload)
    return {
        "message": {
            "items": [
                {
                    "DOI": row["doi"],
                    "URL": row["url"],
                    "container-title": [row["container_title"]],
                    "is-referenced-by-count": row["is_referenced_by_count"],
                    "license": [{"URL": url} for url in row["license_urls"]],
                    "published": (
                        {
                            "date-parts": [
                                [int(part) for part in row["published"].split("-")]
                            ]
                        }
                        if row["published"]
                        else None
                    ),
                    "publisher": row["publisher"],
                    "reference-count": row["reference_count"],
                    "title": [row["title"]],
                    "type": row["type"],
                }
                for row in normalized["results"]
            ],
            "total-results": normalized["total_results"],
        }
    }


def sanitize_get_work_cassette(payload: Any) -> dict[str, Any]:
    row = normalize_get_work(payload)
    return {
        "message": sanitize_search_cassette(
            {"message": {"items": [_denormalize_for_sanitizer(row)], "total-results": 1}}
        )["message"]["items"][0]
    }


def _denormalize_for_sanitizer(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "DOI": row["doi"],
        "URL": row["url"],
        "container-title": [row["container_title"]],
        "is-referenced-by-count": row["is_referenced_by_count"],
        "license": [{"URL": url} for url in row["license_urls"]],
        "published": (
            {"date-parts": [[int(part) for part in str(row["published"]).split("-")]]}
            if row["published"]
            else None
        ),
        "publisher": row["publisher"],
        "reference-count": row["reference_count"],
        "title": [row["title"]],
        "type": row["type"],
    }


SEARCH_WORKS = ToolSpec(
    tool_id="research.search_works",
    provider=PROVIDER,
    name="search_works",
    description_tr=(
        "Crossref'te özet veya tam metin almadan açık bibliyografik eser "
        "metadata'sı arar."
    ),
    parameters=(
        ParamSpec(
            name="query",
            type="string",
            description_tr="Eser başlığı veya konu sorgusu.",
            required=True,
            semantic_type="research_query",
            min_length=2,
            max_length=200,
        ),
        ParamSpec(
            name="work_type",
            type="string",
            description_tr="İsteğe bağlı Crossref eser türü.",
            enum=["journal-article", "book-chapter", "proceedings-article"],
        ),
        ParamSpec(
            name="from_year",
            type="integer",
            description_tr="En erken yayın yılı.",
            minimum=1900,
            maximum=2100,
        ),
        ParamSpec(
            name="sort_by",
            type="string",
            description_tr="Sonuç sıralaması.",
            enum=["relevance", "published"],
            has_default=True,
            default="relevance",
        ),
        ParamSpec(
            name="limit",
            type="integer",
            description_tr="En fazla sonuç.",
            minimum=1,
            maximum=20,
            has_default=True,
            default=5,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Dönen eser sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].doi",
            type="string",
            description_tr="Digital Object Identifier.",
            semantic_type="doi",
        ),
        OutputField(
            path="results[*].title",
            type="string",
            description_tr="Eser başlığı.",
        ),
        OutputField(
            path="results[*].url",
            type="string",
            description_tr="Crossref eser URL'si.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_WORK_METADATA = ToolSpec(
    tool_id="research.get_work_metadata",
    provider=PROVIDER,
    name="get_work_metadata",
    description_tr="DOI ile tek bir eserin güvenli Crossref bibliyografik metadata'sını getirir.",
    parameters=(
        ParamSpec(
            name="doi",
            type="string",
            description_tr="Digital Object Identifier.",
            required=True,
            semantic_type="doi",
            pattern=r"^10\.[0-9]{4,9}/\S+$",
            min_length=7,
            max_length=200,
        ),
    ),
    outputs=(
        OutputField(
            path="doi",
            type="string",
            description_tr="Digital Object Identifier.",
            semantic_type="doi",
        ),
        OutputField(path="title", type="string", description_tr="Eser başlığı."),
        OutputField(path="published", type="string", description_tr="Yayın tarihi."),
        OutputField(path="url", type="string", description_tr="Crossref eser URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_WORKS, GET_WORK_METADATA)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(
            SEARCH_WORKS,
            _search_request,
            normalize_search,
            cassette_sanitizer=sanitize_search_cassette,
        ),
        ToolBinding(
            GET_WORK_METADATA,
            _get_work_request,
            normalize_get_work,
            cassette_sanitizer=sanitize_get_work_cassette,
        ),
    ),
)
