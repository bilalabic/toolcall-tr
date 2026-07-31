"""Wikimedia metadata-only sağlayıcı sınırı."""

from __future__ import annotations

from toolcall_tr.pipeline.environment import build_default_registry
from toolcall_tr.providers.wikimedia.metadata import (
    GET_PAGE_METADATA,
    LIST_PAGE_CATEGORIES,
    SEARCH_PAGES,
    adapter,
    normalize_search,
)


def test_search_istegi_snippet_istemez() -> None:
    binding = adapter.binding(SEARCH_PAGES.tool_id)
    assert binding is not None
    request = binding.build_request({"query": "Fırat Üniversitesi", "limit": 5}, adapter.base_url or "")
    assert request.url.params["srprop"] == "size|wordcount|timestamp"
    assert "snippet" not in request.url.params["srprop"]
    assert request.url.params["srnamespace"] == "0"


def test_search_normalizer_metni_tasimaz() -> None:
    result = normalize_search(
        {
            "query": {
                "searchinfo": {"totalhits": 1},
                "search": [
                    {
                        "pageid": 42,
                        "ns": 0,
                        "title": "Fırat Üniversitesi",
                        "size": 100,
                        "wordcount": 20,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "snippet": "Bu metin çıktıya girmemeli",
                    }
                ],
            }
        }
    )
    assert "snippet" not in result["results"][0]
    assert result["results"][0]["page_id"] == 42


def test_default_registry_wikimedia_araclarini_icerir() -> None:
    registry = build_default_registry()
    for tool in (SEARCH_PAGES, GET_PAGE_METADATA, LIST_PAGE_CATEGORIES):
        assert registry.require(tool.tool_id) == tool
