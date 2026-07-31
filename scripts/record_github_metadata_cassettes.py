"""GitHub public repository metadata-only pilot cassette'lerini kaydeder."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.github_metadata import repositories

ROOT = Path(__file__).resolve().parent.parent / "data" / "cassettes"


def _all_stores(current: CassetteStore) -> list[CassetteStore]:
    return [
        current
        if path.name == repositories.NAMESPACE
        else CassetteStore(ROOT, path.name)
        for path in sorted(item for item in ROOT.iterdir() if item.is_dir())
    ]


def main() -> int:
    with build_http_runtime(
        repositories.adapter,
        cassette_root=ROOT,
        mode=CassetteMode.RECORD_MISSING,
        timeout=60.0,
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        for tool, arguments in (
            (
                repositories.SEARCH_REPOSITORIES,
                {"query": "transformers org:huggingface", "limit": 5},
            ),
            (
                repositories.GET_REPOSITORY_METADATA,
                {"owner": "huggingface", "repository": "transformers"},
            ),
            (
                repositories.LIST_RELEASES_METADATA,
                {"owner": "huggingface", "repository": "transformers", "limit": 5},
            ),
            (
                repositories.GET_REPOSITORY_METADATA,
                {"owner": "openai", "repository": "openai-python"},
            ),
            (
                repositories.GET_REPOSITORY_METADATA,
                {"owner": "pandas-dev", "repository": "pandas"},
            ),
        ):
            result = runtime.executor.execute(tool, arguments)
            if not result.succeeded:
                print(result.error, file=sys.stderr)
                return 1
            print(f"[ok] {tool.tool_id}")

    print(f"MANIFEST.json -> {write_manifest(ROOT, _all_stores(runtime.store))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
