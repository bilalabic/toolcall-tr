"""GitHub metadata-only sağlayıcı sınırı."""

from __future__ import annotations

from toolcall_tr.pipeline.environment import build_default_registry
from toolcall_tr.providers.github_metadata.repositories import (
    GET_REPOSITORY_METADATA,
    LIST_RELEASES_METADATA,
    SEARCH_REPOSITORIES,
    adapter,
    normalize_releases,
    normalize_search,
    sanitize_releases_cassette,
    sanitize_search_cassette,
)


def test_github_istegi_surumu_ve_metadata_media_typeini_sabitler() -> None:
    binding = adapter.binding(SEARCH_REPOSITORIES.tool_id)
    assert binding is not None
    request = binding.build_request({"query": "repo:huggingface/transformers", "limit": 5}, adapter.base_url or "")
    assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.url.params["sort"] == "stars"


def test_repository_normalizer_serbest_metni_tasimaz() -> None:
    row = {
        "id": 1,
        "owner": {"login": "huggingface", "type": "Organization"},
        "name": "transformers",
        "full_name": "huggingface/transformers",
        "html_url": "https://github.com/huggingface/transformers",
        "description": "Çıktıya girmemeli",
        "stargazers_count": 10,
        "license": {"spdx_id": "Apache-2.0"},
    }
    result = normalize_search({"total_count": 1, "items": [row]})
    assert "description" not in result["results"][0]
    assert result["results"][0]["license_spdx"] == "Apache-2.0"


def test_release_normalizer_body_ve_kullaniciyi_tasimaz() -> None:
    result = normalize_releases(
        [
            {
                "id": 1,
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/x/y/releases/1",
                "body": "Çıktıya girmemeli",
                "author": {"login": "someone"},
                "published_at": "2026-01-01T00:00:00Z",
            }
        ]
    )
    assert "body" not in result["results"][0]
    assert "author" not in result["results"][0]


def test_cassette_sanitizer_serbest_metin_ve_profili_diskten_once_atlar() -> None:
    search = sanitize_search_cassette(
        {
            "total_count": 1,
            "items": [
                {
                    "id": 1,
                    "owner": {
                        "login": "org",
                        "type": "Organization",
                        "email": "private@example.com",
                    },
                    "name": "repo",
                    "full_name": "org/repo",
                    "html_url": "https://github.com/org/repo",
                    "description": "serbest metin",
                }
            ],
        }
    )
    assert "description" not in search["items"][0]
    assert search["items"][0]["owner"] == {"login": "org", "type": "Organization"}

    releases = sanitize_releases_cassette(
        [{"id": 1, "tag_name": "v1", "body": "metin", "author": {"login": "kişi"}}]
    )
    assert releases == [
        {
            "id": 1,
            "tag_name": "v1",
            "html_url": None,
            "draft": None,
            "prerelease": None,
            "created_at": None,
            "published_at": None,
        }
    ]


def test_default_registry_github_araclarini_icerir() -> None:
    registry = build_default_registry()
    for tool in (SEARCH_REPOSITORIES, GET_REPOSITORY_METADATA, LIST_RELEASES_METADATA):
        assert registry.require(tool.tool_id) == tool
