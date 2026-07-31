"""GitHub REST API; kullanıcı içeriği olmadan public repository metadata'sı."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import ProviderAdapter, ToolBinding, ToolExecutionError

BASE_URL = "https://api.github.com"
PROVIDER = "github_metadata"
NAMESPACE = "github_metadata"
LICENSE = "GITHUB-METADATA-ONLY"
ATTRIBUTION = "GitHub public repository metadata; kullanıcı metni ve profilleri hariç"
API_VERSION = "2026-03-10"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version=f"github-rest/{API_VERSION}",
    upstream_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }


def _repo_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    owner = row.get("owner")
    if not isinstance(owner, Mapping):
        raise ToolExecutionError("GitHub repository owner metadata'sı eksik")
    if owner.get("type") != "Organization":
        raise ToolExecutionError("Yalnızca GitHub organization repository metadata'sı kabul edilir")
    license_value = row.get("license")
    spdx = license_value.get("spdx_id") if isinstance(license_value, Mapping) else None
    return {
        "repository_id": int(row["id"]),
        "owner_login": str(owner["login"]),
        "name": str(row["name"]),
        "full_name": str(row["full_name"]),
        "html_url": str(row["html_url"]),
        "stars": int(row.get("stargazers_count") or 0),
        "forks": int(row.get("forks_count") or 0),
        "open_issues": int(row.get("open_issues_count") or 0),
        "default_branch": str(row.get("default_branch") or ""),
        "archived": bool(row.get("archived")),
        "fork": bool(row.get("fork")),
        "license_spdx": str(spdx or "NOASSERTION"),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "pushed_at": str(row.get("pushed_at") or ""),
    }


def _safe_repo_raw(row: Mapping[str, Any]) -> dict[str, Any]:
    """GitHub'ın geniş yanıtını yeniden dağıtılabilir metadata alanlarına indirger."""
    owner = row.get("owner")
    license_value = row.get("license")
    return {
        "id": row["id"],
        "owner": (
            {"login": owner["login"], "type": owner.get("type")}
            if isinstance(owner, Mapping)
            else {}
        ),
        "name": row["name"],
        "full_name": row["full_name"],
        "html_url": row["html_url"],
        "stargazers_count": row.get("stargazers_count"),
        "forks_count": row.get("forks_count"),
        "open_issues_count": row.get("open_issues_count"),
        "default_branch": row.get("default_branch"),
        "archived": row.get("archived"),
        "fork": row.get("fork"),
        "license": (
            {"spdx_id": license_value.get("spdx_id")}
            if isinstance(license_value, Mapping)
            else None
        ),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "pushed_at": row.get("pushed_at"),
    }


def sanitize_search_cassette(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        raise ValueError("GitHub search gövdesi geçersiz")
    return {
        "total_count": payload.get("total_count", 0),
        "incomplete_results": payload.get("incomplete_results", False),
        "items": [
            _safe_repo_raw(row)
            for row in payload["items"]
            if isinstance(row, Mapping)
            and isinstance(row.get("owner"), Mapping)
            and row["owner"].get("type") == "Organization"
        ],
    }


def sanitize_repository_cassette(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("GitHub repository gövdesi geçersiz")
    owner = payload.get("owner")
    if not isinstance(owner, Mapping) or owner.get("type") != "Organization":
        raise ValueError("GitHub organization repository gövdesi bekleniyordu")
    return _safe_repo_raw(payload)


def sanitize_releases_cassette(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("GitHub release gövdesi geçersiz")
    return [
        {
            "id": row["id"],
            "tag_name": row.get("tag_name"),
            "html_url": row.get("html_url"),
            "draft": row.get("draft"),
            "prerelease": row.get("prerelease"),
            "created_at": row.get("created_at"),
            "published_at": row.get("published_at"),
        }
        for row in payload
        if isinstance(row, Mapping) and row.get("id") is not None
    ]


def _search_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/search/repositories",
        params={
            "q": arguments["query"],
            "sort": "stars",
            "order": "desc",
            "per_page": arguments.get("limit", 5),
            "page": 1,
        },
        headers=_headers(),
    )


def normalize_search(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ToolExecutionError("GitHub repository search yanıtı geçersiz")
    results = [_repo_metadata(row) for row in payload["items"] if isinstance(row, Mapping)]
    return {
        "total_count": int(payload.get("total_count") or 0),
        "count": len(results),
        "results": results,
    }


def _repository_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    owner = str(arguments["owner"])
    repository = str(arguments["repository"])
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/repos/{owner}/{repository}",
        headers=_headers(),
    )


def normalize_repository(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("id") is None:
        raise ToolExecutionError("GitHub repository yanıtı geçersiz")
    return _repo_metadata(payload)


def _releases_request(arguments: Mapping[str, Any], base_url: str) -> httpx.Request:
    owner = str(arguments["owner"])
    repository = str(arguments["repository"])
    return httpx.Request(
        "GET",
        f"{base_url.rstrip('/')}/repos/{owner}/{repository}/releases",
        params={"per_page": arguments.get("limit", 5), "page": 1},
        headers=_headers(),
    )


def normalize_releases(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ToolExecutionError("GitHub releases yanıtı geçersiz")
    results = [
        {
            "release_id": int(row["id"]),
            "tag_name": str(row.get("tag_name") or ""),
            "html_url": str(row.get("html_url") or ""),
            "draft": bool(row.get("draft")),
            "prerelease": bool(row.get("prerelease")),
            "created_at": str(row.get("created_at") or ""),
            "published_at": str(row.get("published_at") or ""),
        }
        for row in payload
        if isinstance(row, dict) and row.get("id") is not None
    ]
    return {"count": len(results), "results": results}


SEARCH_REPOSITORIES = ToolSpec(
    tool_id="developer.search_repositories",
    provider=PROVIDER,
    name="search_repositories",
    description_tr="GitHub'da kullanıcı metni olmadan public organization repository metadata'sı arar.",
    parameters=(
        ParamSpec(name="query", type="string", description_tr="Repository arama sorgusu.", required=True, min_length=2),
        ParamSpec(name="limit", type="integer", description_tr="En fazla sonuç.", minimum=1, maximum=10, has_default=True, default=5),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Dönen repository sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].owner_login", type="string", description_tr="Repository sahibi.", semantic_type="repository_owner"),
        OutputField(path="results[*].name", type="string", description_tr="Repository adı.", semantic_type="repository_name"),
        OutputField(path="results[*].full_name", type="string", description_tr="owner/name biçimi."),
        OutputField(path="results[*].html_url", type="string", description_tr="Repository URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

GET_REPOSITORY_METADATA = ToolSpec(
    tool_id="developer.get_repository_metadata",
    provider=PROVIDER,
    name="get_repository_metadata",
    description_tr="Public bir GitHub organization repository'sinin güvenli metadata alanlarını getirir.",
    parameters=(
        ParamSpec(name="owner", type="string", description_tr="Repository sahibi.", required=True, semantic_type="repository_owner"),
        ParamSpec(name="repository", type="string", description_tr="Repository adı.", required=True, semantic_type="repository_name"),
    ),
    outputs=(
        OutputField(path="repository_id", type="integer", description_tr="GitHub repository kimliği."),
        OutputField(path="full_name", type="string", description_tr="owner/name biçimi."),
        OutputField(path="stars", type="integer", description_tr="Yıldız sayısı."),
        OutputField(path="license_spdx", type="string", description_tr="Beyan edilen SPDX lisans kimliği."),
        OutputField(path="html_url", type="string", description_tr="Repository URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    source=_SOURCE,
)

LIST_RELEASES_METADATA = ToolSpec(
    tool_id="developer.list_releases_metadata",
    provider=PROVIDER,
    name="list_releases_metadata",
    description_tr="Public bir GitHub repository'sinin release gövdesi olmadan sürüm metadata'sını listeler.",
    parameters=(
        ParamSpec(name="owner", type="string", description_tr="Repository sahibi.", required=True, semantic_type="repository_owner"),
        ParamSpec(name="repository", type="string", description_tr="Repository adı.", required=True, semantic_type="repository_name"),
        ParamSpec(name="limit", type="integer", description_tr="En fazla release.", minimum=1, maximum=10, has_default=True, default=5),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Release sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].release_id", type="integer", description_tr="GitHub release kimliği."),
        OutputField(path="results[*].tag_name", type="string", description_tr="Git etiketi."),
        OutputField(path="results[*].published_at", type="string", description_tr="Yayın zamanı."),
        OutputField(path="results[*].html_url", type="string", description_tr="Release URL'si."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.LIVE_RECORDED,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (
    SEARCH_REPOSITORIES,
    GET_REPOSITORY_METADATA,
    LIST_RELEASES_METADATA,
)
adapter = ProviderAdapter(
    name=PROVIDER,
    base_url=BASE_URL,
    license=LICENSE,
    attribution=ATTRIBUTION,
    cassette_namespace=NAMESPACE,
    bindings=(
        ToolBinding(
            SEARCH_REPOSITORIES,
            _search_request,
            normalize_search,
            sanitize_search_cassette,
        ),
        ToolBinding(
            GET_REPOSITORY_METADATA,
            _repository_request,
            normalize_repository,
            sanitize_repository_cassette,
        ),
        ToolBinding(
            LIST_RELEASES_METADATA,
            _releases_request,
            normalize_releases,
            sanitize_releases_cassette,
        ),
    ),
)
