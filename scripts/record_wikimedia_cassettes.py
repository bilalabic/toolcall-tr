"""Türkçe Vikipedi metadata-only pilot cassette'lerini kaydeder."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.wikimedia import metadata

ROOT = Path(__file__).resolve().parent.parent / "data" / "cassettes"


def _all_stores(current: CassetteStore) -> list[CassetteStore]:
    return [
        current if path.name == metadata.NAMESPACE else CassetteStore(ROOT, path.name)
        for path in sorted(item for item in ROOT.iterdir() if item.is_dir())
    ]


def main() -> int:
    with build_http_runtime(
        metadata.adapter,
        cassette_root=ROOT,
        mode=CassetteMode.RECORD_MISSING,
        timeout=60.0,
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        istanbul = runtime.executor.execute(
            metadata.SEARCH_PAGES,
            {"query": "İstanbul", "limit": 5},
        )
        if not istanbul.succeeded:
            print(istanbul.error, file=sys.stderr)
            return 1
        print("[ok] knowledge.search_pages: Istanbul")

        search = runtime.executor.execute(
            metadata.SEARCH_PAGES,
            {"query": "Fırat Üniversitesi", "limit": 5},
        )
        if not search.succeeded or not search.response["results"]:
            print(search.error or "Sayfa bulunamadı", file=sys.stderr)
            return 1
        page_id = search.response["results"][0]["page_id"]
        for tool, arguments in (
            (metadata.GET_PAGE_METADATA, {"page_id": page_id}),
            (metadata.LIST_PAGE_CATEGORIES, {"page_id": page_id, "limit": 20}),
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
