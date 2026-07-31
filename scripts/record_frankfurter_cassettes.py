"""Frankfurter v2 ECB-pinned pilot cassette'lerini kaydeder."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.frankfurter import rates

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT = REPO_ROOT / "data" / "cassettes"

CALLS = (
    (rates.GET_EXCHANGE_RATE, {"base": "TRY", "quote": "EUR"}),
    (rates.GET_EXCHANGE_RATE, {"base": "USD", "quote": "TRY"}),
    (
        rates.GET_HISTORICAL_EXCHANGE_RATE,
        {"base": "TRY", "quote": "EUR", "date": "2025-01-02"},
    ),
    (
        rates.GET_HISTORICAL_EXCHANGE_RATE,
        {"base": "EUR", "quote": "USD", "date": "2025-06-30"},
    ),
    (rates.LIST_SUPPORTED_CURRENCIES, {}),
)


def _all_stores(current: CassetteStore) -> list[CassetteStore]:
    return [
        current if path.name == rates.NAMESPACE else CassetteStore(ROOT, path.name)
        for path in sorted(item for item in ROOT.iterdir() if item.is_dir())
    ]


def main() -> int:
    failures = 0
    with build_http_runtime(
        rates.adapter,
        cassette_root=ROOT,
        mode=CassetteMode.RECORD_MISSING,
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        for tool, arguments in CALLS:
            result = runtime.executor.execute(tool, arguments)
            print(f"[{'ok' if result.succeeded else 'KIRIK'}] {tool.tool_id}")
            if not result.succeeded:
                failures += 1
                print(result.error, file=sys.stderr)

    print(f"MANIFEST.json -> {write_manifest(ROOT, _all_stores(runtime.store))}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
