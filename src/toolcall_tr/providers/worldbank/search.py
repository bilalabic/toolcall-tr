"""İncelenmiş WDI gösterge allowlist'i üzerinde yerel arama."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from toolcall_tr.canonical import sha256_hex
from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import LocalProviderAdapter, LocalToolBinding
from toolcall_tr.turkish.text import ascii_fold_tr, casefold_tr

PROVIDER = "wdi_allowlist"
LICENSE = "CC-BY-4.0-WORLD-BANK-TERMS"
ATTRIBUTION = "World Bank, World Development Indicators"

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="wdi-indicators/2026-07",
    upstream_url="https://api.worldbank.org/v2/source/2",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

SEARCH_INDICATOR = ToolSpec(
    tool_id="statistics.search_indicator",
    provider=PROVIDER,
    name="search_indicator",
    description_tr="Yayın için incelenmiş World Development Indicators göstergelerini arar.",
    parameters=(
        ParamSpec(name="query", type="string", description_tr="Gösterge adı veya kodu.", required=True, min_length=2),
    ),
    outputs=(
        OutputField(path="count", type="integer", description_tr="Eşleşme sayısı.", semantic_type="result_count"),
        OutputField(path="results[*].code", type="string", description_tr="WDI gösterge kodu.", semantic_type="indicator_code"),
        OutputField(path="results[*].name_tr", type="string", description_tr="Göstergenin Türkçe adı."),
        OutputField(path="results[*].source_id", type="integer", description_tr="World Bank kaynak kimliği."),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

TOOLS = (SEARCH_INDICATOR,)


def build_adapter(snapshot_dir: Path) -> LocalProviderAdapter:
    manifest = json.loads((snapshot_dir / "SNAPSHOT.json").read_text(encoding="utf-8"))
    path = snapshot_dir / "indicators.jsonl"
    digest = sha256_hex(path.read_bytes())
    if digest != manifest["content_hash"]:
        raise ValueError("WDI allowlist hash uyuşmazlığı")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != manifest["row_count"]:
        raise ValueError("WDI allowlist satır sayısı uyuşmuyor")

    def run(arguments: Mapping[str, Any]) -> dict[str, Any]:
        needle = ascii_fold_tr(casefold_tr(str(arguments["query"]))).casefold()
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for row in rows:
            searchable = ascii_fold_tr(
                casefold_tr(f"{row['code']} {row['name_tr']}")
            ).casefold()
            if needle not in searchable:
                continue
            tokens = searchable.replace("(", " ").replace(")", " ").split()
            score = 0 if needle in tokens else 1
            scored.append((score, row["code"], row))
        scored.sort(key=lambda item: (item[0], item[1]))
        found = [row for _, _, row in scored]
        return {"count": len(found), "results": found}

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes={"wdi_indicators": digest},
        bindings=(LocalToolBinding(SEARCH_INDICATOR, run),),
    )
