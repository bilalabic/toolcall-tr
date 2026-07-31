"""Wikidata Action API; yalnızca CC0 yapılandırılmış entity metadata'sı."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

__all__ = [
    "GET_ENTITY_FACTS",
    "LIST_ENTITY_RELATIONS",
    "SEARCH_ENTITIES",
    "TOOLS",
    "adapter",
]

BASE_URL = "https://www.wikidata.org"
PROVIDER = "wikidata"
NAMESPACE = "wikidata"
LICENSE = "CC0-1.0"
ATTRIBUTION = "Wikidata contributors, structured data under CC0 1.0"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version="wikidata-action-api/2026-07",
    upstream_url=f"{BASE_URL}/w/api.php",
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _common() -> dict[str, Any]:
    return {"action": "wbgetentities", "format": "json", "formatversion": 2}


def _search_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/w/api.php",
        params={
            "action": "wbsearchentities",
            "format": "json",
            "formatversion": 2,
            "search": arguments["query"],
            "language": arguments.get("language", "tr"),
            "uselang": "tr",
            "type": "item",
            "limit": arguments.get("limit", 5),
        },
    )


def normalize_search(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("search"), list):
        raise ToolExecutionError("Wikidata entity arama yanıtı geçersiz")
    results = []
    for row in payload["search"]:
        if not isinstance(row, Mapping) or not row.get("id"):
            continue
        match = row.get("match")
        results.append(
            {
                "concept_url": str(row.get("concepturi") or ""),
                "description": str(row.get("description") or ""),
                "entity_id": str(row["id"]),
                "label": str(row.get("label") or ""),
                "match_language": (
                    str(match.get("language") or "")
                    if isinstance(match, Mapping)
                    else ""
                ),
                "repository": str(row.get("repository") or "wikidata"),
            }
        )
    return {
        "count": len(results),
        "has_more": bool(payload.get("search-continue") is not None),
        "results": results,
    }


def _facts_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    languages = arguments.get("languages", ["tr", "en"])
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/w/api.php",
        params={
            **_common(),
            "ids": arguments["entity_id"],
            "languages": "|".join(str(item) for item in languages),
            "props": "labels|descriptions|aliases|sitelinks",
            "sitefilter": "trwiki|enwiki",
        },
    )


def _entity(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("entities"), Mapping):
        raise ToolExecutionError("Wikidata entity yanıtı geçersiz")
    entities = payload["entities"]
    if not entities:
        raise ToolExecutionError("Wikidata entity bulunamadı", status_code=404)
    entity = next(iter(entities.values()))
    if not isinstance(entity, Mapping) or entity.get("missing"):
        raise ToolExecutionError("Wikidata entity bulunamadı", status_code=404)
    return entity


def _language_values(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(language): str(item.get("value") or "")
        for language, item in value.items()
        if isinstance(item, Mapping)
    }


def normalize_facts(payload: Any) -> dict[str, Any]:
    entity = _entity(payload)
    aliases_raw = entity.get("aliases")
    aliases: dict[str, list[str]] = {}
    if isinstance(aliases_raw, Mapping):
        for language, values in aliases_raw.items():
            if isinstance(values, list):
                aliases[str(language)] = [
                    str(item.get("value") or "")
                    for item in values
                    if isinstance(item, Mapping) and item.get("value")
                ]
    sitelinks_raw = entity.get("sitelinks")
    sitelinks = {}
    if isinstance(sitelinks_raw, Mapping):
        sitelinks = {
            str(site): {
                "site": str(item.get("site") or site),
                "title": str(item.get("title") or ""),
            }
            for site, item in sitelinks_raw.items()
            if isinstance(item, Mapping)
        }
    return {
        "aliases": aliases,
        "descriptions": _language_values(entity.get("descriptions")),
        "entity_id": str(entity["id"]),
        "labels": _language_values(entity.get("labels")),
        "last_revision_id": int(entity.get("lastrevid") or 0),
        "modified": str(entity.get("modified") or ""),
        "sitelinks": sitelinks,
        "type": str(entity.get("type") or "item"),
    }


def _relations_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/w/api.php",
        params={
            **_common(),
            "ids": arguments["entity_id"],
            "props": "claims",
        },
    )


def normalize_relations(payload: Any) -> dict[str, Any]:
    entity = _entity(payload)
    claims = entity.get("claims")
    if not isinstance(claims, Mapping):
        claims = {}
    relations = []
    for property_id, statements in claims.items():
        if not isinstance(statements, list):
            continue
        for statement in statements:
            if not isinstance(statement, Mapping):
                continue
            mainsnak = statement.get("mainsnak")
            if not isinstance(mainsnak, Mapping):
                continue
            datavalue = mainsnak.get("datavalue")
            if not isinstance(datavalue, Mapping):
                continue
            value = datavalue.get("value")
            if not isinstance(value, Mapping) or value.get("entity-type") != "item":
                continue
            numeric_id = value.get("numeric-id")
            if numeric_id is None:
                continue
            relations.append(
                {
                    "property_id": str(property_id),
                    "rank": str(statement.get("rank") or "normal"),
                    "target_entity_id": f"Q{int(numeric_id)}",
                }
            )
    relations.sort(
        key=lambda row: (
            row["property_id"],
            row["target_entity_id"],
        )
    )
    return {
        "count": len(relations),
        "entity_id": str(entity["id"]),
        "relations": relations,
    }


def sanitize_search_cassette(payload: Any) -> dict[str, Any]:
    normalized = normalize_search(payload)
    return {
        "search": [
            {
                "concepturi": row["concept_url"],
                "description": row["description"],
                "id": row["entity_id"],
                "label": row["label"],
                "match": {"language": row["match_language"]},
                "repository": row["repository"],
            }
            for row in normalized["results"]
        ],
        "search-continue": 1 if normalized["has_more"] else None,
    }


def sanitize_facts_cassette(payload: Any) -> dict[str, Any]:
    normalized = normalize_facts(payload)
    entity_id = normalized["entity_id"]
    return {
        "entities": {
            entity_id: {
                "aliases": {
                    language: [
                        {"language": language, "value": value}
                        for value in values
                    ]
                    for language, values in normalized["aliases"].items()
                },
                "descriptions": {
                    language: {"language": language, "value": value}
                    for language, value in normalized["descriptions"].items()
                },
                "id": entity_id,
                "labels": {
                    language: {"language": language, "value": value}
                    for language, value in normalized["labels"].items()
                },
                "lastrevid": normalized["last_revision_id"],
                "modified": normalized["modified"],
                "sitelinks": normalized["sitelinks"],
                "type": normalized["type"],
            }
        }
    }


def sanitize_relations_cassette(payload: Any) -> dict[str, Any]:
    normalized = normalize_relations(payload)
    claims: dict[str, list[dict[str, Any]]] = {}
    for relation in normalized["relations"]:
        claims.setdefault(relation["property_id"], []).append(
            {
                "mainsnak": {
                    "datavalue": {
                        "value": {
                            "entity-type": "item",
                            "numeric-id": int(
                                relation["target_entity_id"].removeprefix("Q")
                            ),
                        }
                    }
                },
                "rank": relation["rank"],
            }
        )
    entity_id = normalized["entity_id"]
    return {"entities": {entity_id: {"claims": claims, "id": entity_id}}}


SEARCH_ENTITIES = ToolSpec(
    tool_id="knowledge.search_entities",
    provider=PROVIDER,
    name="search_entities",
    description_tr="Wikidata'da Türkçe veya İngilizce CC0 entity metadata'sı arar.",
    parameters=(
        ParamSpec(
            name="query",
            type="string",
            description_tr="Entity arama sorgusu.",
            required=True,
            semantic_type="entity_query",
            min_length=2,
            max_length=120,
        ),
        ParamSpec(
            name="language",
            type="string",
            description_tr="Arama dili.",
            enum=["tr", "en"],
            has_default=True,
            default="tr",
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
            description_tr="Dönen entity sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="results[*].entity_id",
            type="string",
            description_tr="Wikidata Q kimliği.",
            semantic_type="entity_id",
        ),
        OutputField(
            path="results[*].label",
            type="string",
            description_tr="Entity etiketi.",
        ),
        OutputField(
            path="results[*].concept_url",
            type="string",
            description_tr="Wikidata entity URL'si.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_ENTITY_FACTS = ToolSpec(
    tool_id="knowledge.get_entity_facts",
    provider=PROVIDER,
    name="get_entity_facts",
    description_tr=(
        "Bir Wikidata entity'sinin etiket, kısa açıklama, takma ad ve "
        "sitelink metadata'sını getirir."
    ),
    parameters=(
        ParamSpec(
            name="entity_id",
            type="string",
            description_tr="Wikidata Q kimliği.",
            required=True,
            semantic_type="entity_id",
            pattern=r"^Q[1-9][0-9]*$",
        ),
        ParamSpec(
            name="languages",
            type="array",
            item_type="string",
            description_tr="Döndürülecek dil kodları.",
            min_items=1,
            max_items=3,
            has_default=True,
            default=["tr", "en"],
        ),
    ),
    outputs=(
        OutputField(
            path="entity_id",
            type="string",
            description_tr="Wikidata Q kimliği.",
            semantic_type="entity_id",
        ),
        OutputField(
            path="labels",
            type="object",
            description_tr="Dil koduna göre etiketler.",
        ),
        OutputField(
            path="descriptions",
            type="object",
            description_tr="Dil koduna göre kısa açıklamalar.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

LIST_ENTITY_RELATIONS = ToolSpec(
    tool_id="knowledge.list_entity_relations",
    provider=PROVIDER,
    name="list_entity_relations",
    description_tr="Bir Wikidata entity'sinin başka item'lara giden yapılandırılmış ilişkilerini listeler.",
    parameters=(
        ParamSpec(
            name="entity_id",
            type="string",
            description_tr="Wikidata Q kimliği.",
            required=True,
            semantic_type="entity_id",
            pattern=r"^Q[1-9][0-9]*$",
        ),
    ),
    outputs=(
        OutputField(
            path="entity_id",
            type="string",
            description_tr="Kaynak entity kimliği.",
            semantic_type="entity_id",
        ),
        OutputField(
            path="count",
            type="integer",
            description_tr="İlişki sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="relations[*].property_id",
            type="string",
            description_tr="Wikidata property kimliği.",
            semantic_type="property_id",
        ),
        OutputField(
            path="relations[*].target_entity_id",
            type="string",
            description_tr="Hedef Wikidata entity kimliği.",
            semantic_type="entity_id",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (
    SEARCH_ENTITIES,
    GET_ENTITY_FACTS,
    LIST_ENTITY_RELATIONS,
)

adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(
            SEARCH_ENTITIES,
            _search_request,
            normalize_search,
            cassette_sanitizer=sanitize_search_cassette,
        ),
        ToolBinding(
            GET_ENTITY_FACTS,
            _facts_request,
            normalize_facts,
            cassette_sanitizer=sanitize_facts_cassette,
        ),
        ToolBinding(
            LIST_ENTITY_RELATIONS,
            _relations_request,
            normalize_relations,
            cassette_sanitizer=sanitize_relations_cassette,
        ),
    ),
)
