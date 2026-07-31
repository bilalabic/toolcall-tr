"""Wikidata ve Crossref için küçük, Türkiye odaklı metadata cassette'leri.

Yalnız yapılandırılmış/metadata alanları provider sanitizer'larından geçerek
kaydedilir; makale metni, abstract, snippet veya kullanıcı içeriği tutulmaz.
"""

from __future__ import annotations

import sys
from pathlib import Path

from toolcall_tr.execution.cassette import CassetteMode, CassetteStore, write_manifest
from toolcall_tr.execution.environment import build_http_runtime
from toolcall_tr.providers.crossref import works
from toolcall_tr.providers.wikidata import entities

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_ROOT = REPO_ROOT / "data" / "cassettes"


def _all_stores(
    wikidata_store: CassetteStore,
    crossref_store: CassetteStore,
) -> list[CassetteStore]:
    stores: list[CassetteStore] = []
    replacements = {
        entities.NAMESPACE: wikidata_store,
        works.NAMESPACE: crossref_store,
    }
    for path in sorted(item for item in CASSETTE_ROOT.iterdir() if item.is_dir()):
        stores.append(replacements.get(path.name, CassetteStore(CASSETTE_ROOT, path.name)))
    for namespace, store in replacements.items():
        if not (CASSETTE_ROOT / namespace).is_dir():
            stores.append(store)
    return stores


def main() -> int:
    failures = 0
    with (
        build_http_runtime(
            entities.adapter,
            cassette_root=CASSETTE_ROOT,
            mode=CassetteMode.RECORD_MISSING,
        ) as wikidata_runtime,
        build_http_runtime(
            works.adapter,
            cassette_root=CASSETTE_ROOT,
            mode=CassetteMode.RECORD_MISSING,
        ) as crossref_runtime,
    ):
        wikidata_runtime.client.headers["Accept-Encoding"] = "identity"
        crossref_runtime.client.headers["Accept-Encoding"] = "identity"
        entity_search = wikidata_runtime.executor.execute(
            entities.SEARCH_ENTITIES,
            {"query": "Anıtkabir", "language": "tr", "limit": 5},
        )
        if not entity_search.succeeded or not entity_search.response["results"]:
            print(f"[KIRIK] Wikidata arama: {entity_search.error}", file=sys.stderr)
            failures += 1
        else:
            entity_id = entity_search.response["results"][0]["entity_id"]
            for tool, arguments in (
                (entities.GET_ENTITY_FACTS, {"entity_id": entity_id}),
                (entities.LIST_ENTITY_RELATIONS, {"entity_id": entity_id}),
            ):
                result = wikidata_runtime.executor.execute(tool, arguments)
                if not result.succeeded:
                    failures += 1
                    print(f"[KIRIK] {tool.tool_id}: {result.error}", file=sys.stderr)
            print(f"[ok] Wikidata Anıtkabir -> {entity_id}")

        work_search = crossref_runtime.executor.execute(
            works.SEARCH_WORKS,
            {"query": "2023 Kahramanmaraş depremleri Türkiye"},
        )
        if not work_search.succeeded or not work_search.response["results"]:
            print(f"[KIRIK] Crossref arama: {work_search.error}", file=sys.stderr)
            failures += 1
        else:
            doi = work_search.response["results"][0]["doi"]
            metadata = crossref_runtime.executor.execute(
                works.GET_WORK_METADATA,
                {"doi": doi},
            )
            if not metadata.succeeded:
                failures += 1
                print(f"[KIRIK] Crossref metadata: {metadata.error}", file=sys.stderr)
            print(f"[ok] Crossref ilk DOI -> {doi}")

    digest = write_manifest(
        CASSETTE_ROOT,
        _all_stores(wikidata_runtime.store, crossref_runtime.store),
    )
    print(f"MANIFEST.json -> {digest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
