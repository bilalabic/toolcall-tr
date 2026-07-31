"""GBIF pilot cassette'lerini lisans filtreli isteklerle kaydeder."""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.gbif import biodiversity

ROOT = Path(__file__).resolve().parent.parent / "data" / "cassettes"


def _all_stores(current: CassetteStore) -> list[CassetteStore]:
    return [
        current if path.name == biodiversity.NAMESPACE else CassetteStore(ROOT, path.name)
        for path in sorted(item for item in ROOT.iterdir() if item.is_dir())
    ]


def main() -> int:
    with build_http_runtime(
        biodiversity.adapter,
        cassette_root=ROOT,
        mode=CassetteMode.RECORD_MISSING,
        timeout=60.0,
    ) as runtime:
        runtime.client.headers["Accept-Encoding"] = "identity"
        for scientific_name in ("Quercus robur", "Panthera leo", "Canis lupus"):
            result = runtime.executor.execute(
                biodiversity.MATCH_SPECIES_NAME,
                {"scientific_name": scientific_name},
            )
            if not result.succeeded:
                print(result.error, file=sys.stderr)
                return 1
            print(f"[ok] {biodiversity.MATCH_SPECIES_NAME.tool_id}: {scientific_name}")

        oak = runtime.executor.execute(
            biodiversity.MATCH_SPECIES_NAME,
            {"scientific_name": "Quercus robur"},
        )
        taxon_key = oak.response["usage_key"]
        for tool, arguments in (
            (biodiversity.GET_SPECIES, {"taxon_key": taxon_key}),
            (
                biodiversity.SEARCH_OCCURRENCES,
                {"taxon_key": taxon_key, "country_code": "TR", "limit": 5},
            ),
        ):
            result = runtime.executor.execute(tool, arguments)
            if not result.succeeded:
                print(result.error, file=sys.stderr)
                return 1

    print(f"MANIFEST.json -> {write_manifest(ROOT, _all_stores(runtime.store))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
