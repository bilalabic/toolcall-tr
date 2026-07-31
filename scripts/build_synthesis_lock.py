"""Sentez template'lerini derler ve incelenebilir lockfile yazar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from toolcall_tr.generation.synthesis import synthesis_catalog_lock

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "synthesis"
OUT = CATALOG / "LOCK.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Katalogdan alınacak deterministik blueprint ön eki.",
    )
    args = parser.parse_args()
    lock = synthesis_catalog_lock(CATALOG, limit=args.limit)
    OUT.write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{lock['blueprint_count']} blueprint -> {OUT}")


if __name__ == "__main__":
    main()
