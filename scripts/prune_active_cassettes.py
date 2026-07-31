"""Aktif blueprintlerin tüketmediği cassette kayıtlarını güvenle budar."""

from __future__ import annotations

from pathlib import Path

from toolcall_tr.execution.cassette import CassetteStore, write_manifest
from toolcall_tr.groundtruth.planner import plan
from toolcall_tr.groundtruth.runner import run
from toolcall_tr.pipeline.blueprints import load_blueprints
from toolcall_tr.pipeline.environment import open_default_environment

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_ROOT = REPO_ROOT / "data" / "cassettes"


def main() -> None:
    blueprints = load_blueprints(REPO_ROOT / "data" / "blueprints")
    with open_default_environment(repo_root=REPO_ROOT) as environment:
        for blueprint in blueprints:
            run(plan(blueprint, environment.registry), environment)

        used = set(environment.used_cassette_keys)
        active_stores = {
            transport.store.namespace: transport.store
            for transport in environment.cassettes
        }
        removed: dict[str, tuple[str, ...]] = {}
        for namespace, store in active_stores.items():
            pruned = store.prune(used)
            if pruned:
                removed[namespace] = pruned

        stores = [
            active_stores.get(path.name, CassetteStore(CASSETTE_ROOT, path.name))
            for path in sorted(item for item in CASSETTE_ROOT.iterdir() if item.is_dir())
        ]
        digest = write_manifest(CASSETTE_ROOT, stores)

    for namespace, keys in sorted(removed.items()):
        print(f"{namespace}: {len(keys)} kayıt budandı")
        for key in keys:
            print(f"  {key}")
    print(f"MANIFEST.json -> {digest}")


if __name__ == "__main__":
    main()
