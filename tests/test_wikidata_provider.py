"""Wikidata CC0 metadata sağlayıcısı."""

from __future__ import annotations

from toolcall_tr.providers.wikidata.entities import (
    GET_ENTITY_FACTS,
    LIST_ENTITY_RELATIONS,
    SEARCH_ENTITIES,
    adapter,
    normalize_facts,
    normalize_relations,
    normalize_search,
)


def test_search_request_turkce_ve_metadata_only() -> None:
    binding = adapter.binding(SEARCH_ENTITIES.tool_id)
    assert binding is not None
    request = binding.build_request(
        {"query": "Ankara", "language": "tr", "limit": 5},
        adapter.base_url or "",
    )
    assert request.url.params["action"] == "wbsearchentities"
    assert request.url.params["language"] == "tr"
    assert request.url.params["type"] == "item"


def test_search_normalizer() -> None:
    result = normalize_search(
        {
            "search": [
                {
                    "id": "Q3640",
                    "label": "Ankara",
                    "description": "Türkiye'nin başkenti",
                    "concepturi": "http://www.wikidata.org/entity/Q3640",
                    "repository": "wikidata",
                    "match": {"language": "tr", "type": "label", "text": "Ankara"},
                }
            ]
        }
    )
    assert result["results"][0]["entity_id"] == "Q3640"
    assert result["results"][0]["label"] == "Ankara"


def test_facts_normalizer_yalniz_metadata_tasir() -> None:
    result = normalize_facts(
        {
            "entities": {
                "Q3640": {
                    "id": "Q3640",
                    "type": "item",
                    "lastrevid": 123,
                    "modified": "2026-07-01T00:00:00Z",
                    "labels": {"tr": {"language": "tr", "value": "Ankara"}},
                    "descriptions": {
                        "tr": {"language": "tr", "value": "Türkiye'nin başkenti"}
                    },
                    "aliases": {"tr": [{"language": "tr", "value": "Ankara ili"}]},
                    "sitelinks": {"trwiki": {"site": "trwiki", "title": "Ankara"}},
                }
            }
        }
    )
    assert result["entity_id"] == "Q3640"
    assert result["labels"] == {"tr": "Ankara"}
    assert "claims" not in result


def test_relations_yalniz_entity_hedeflerini_alir() -> None:
    result = normalize_relations(
        {
            "entities": {
                "Q3640": {
                    "id": "Q3640",
                    "claims": {
                        "P17": [
                            {
                                "id": "Q3640$1",
                                "rank": "normal",
                                "mainsnak": {
                                    "datavalue": {
                                        "value": {
                                            "entity-type": "item",
                                            "numeric-id": 43,
                                        }
                                    }
                                },
                            }
                        ],
                        "P1082": [
                            {
                                "id": "Q3640$2",
                                "mainsnak": {"datavalue": {"value": {"amount": "+1"}}},
                            }
                        ],
                    },
                }
            }
        }
    )
    assert result["relations"] == [
        {
            "property_id": "P17",
            "rank": "normal",
            "target_entity_id": "Q43",
        }
    ]


def test_tools_cc0_ve_canli_kayitli() -> None:
    assert {tool.tool_id for tool in adapter.tools} == {
        SEARCH_ENTITIES.tool_id,
        GET_ENTITY_FACTS.tool_id,
        LIST_ENTITY_RELATIONS.tool_id,
    }
    assert all(tool.source.license == "CC0-1.0" for tool in adapter.tools)
