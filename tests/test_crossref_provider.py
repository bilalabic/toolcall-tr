"""Crossref bibliyografik metadata sağlayıcısı."""

from __future__ import annotations

from toolcall_tr.providers.crossref.works import (
    GET_WORK_METADATA,
    SEARCH_WORKS,
    adapter,
    normalize_get_work,
    normalize_search,
    sanitize_search_cassette,
)


def _work() -> dict[str, object]:
    return {
        "DOI": "10.1000/example",
        "URL": "https://doi.org/10.1000/example",
        "abstract": "Bu alan veri setine girmemeli.",
        "container-title": ["Örnek Dergi"],
        "is-referenced-by-count": 12,
        "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        "published": {"date-parts": [[2026, 7, 1]]},
        "publisher": "Örnek Yayıncı",
        "reference-count": 8,
        "title": ["Türkiye'de Yapay Zekâ"],
        "type": "journal-article",
    }


def test_search_request_ozet_istemez() -> None:
    binding = adapter.binding(SEARCH_WORKS.tool_id)
    assert binding is not None
    request = binding.build_request(
        {
            "query": "Türkiye yapay zekâ",
            "work_type": "journal-article",
            "from_year": 2020,
            "sort_by": "published",
            "limit": 5,
        },
        adapter.base_url or "",
    )
    assert "abstract" not in request.url.params["select"]
    assert request.url.params["filter"] == "from-pub-date:2020-01-01,type:journal-article"
    assert request.url.params["sort"] == "published"


def test_search_normalizer_abstracti_atar() -> None:
    result = normalize_search(
        {"message": {"items": [_work()], "total-results": 1}}
    )
    row = result["results"][0]
    assert row["doi"] == "10.1000/example"
    assert row["published"] == "2026-07-01"
    assert "abstract" not in row


def test_get_work_normalizer() -> None:
    result = normalize_get_work({"message": _work()})
    assert result["title"] == "Türkiye'de Yapay Zekâ"
    assert result["container_title"] == "Örnek Dergi"


def test_cassette_sanitizer_ham_metni_tutmaz() -> None:
    result = sanitize_search_cassette(
        {"message": {"items": [_work()], "total-results": 1}}
    )
    assert "abstract" not in result["message"]["items"][0]


def test_tool_katalogu_iki_arac() -> None:
    assert {tool.tool_id for tool in adapter.tools} == {
        SEARCH_WORKS.tool_id,
        GET_WORK_METADATA.tool_id,
    }
