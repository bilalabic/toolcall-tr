from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.factories import make_blueprint
from toolcall_tr.cli.main import _canary_budget_config
from toolcall_tr.generation import allocate_canary, rebalance_canary
from toolcall_tr.models import Split
from toolcall_tr.pipeline.blueprints import load_blueprints


def _blueprints():
    return tuple(
        make_blueprint(
            blueprint_id=f"canary_blueprint_{index}",
            family_id=f"canary_family_{index}",
            split=split,
        )
        for index, split in enumerate(
            (Split.TRAIN, Split.TRAIN, Split.VALIDATION, Split.TEST),
            start=1,
        )
    )


def test_canary_tam_hedef_ve_split_butcesi_uretir() -> None:
    allocations = allocate_canary(_blueprints(), target=1_000)

    assert len(allocations) == 1_000
    assert Counter(item.blueprint.split for item in allocations) == {
        Split.TRAIN: 700,
        Split.VALIDATION: 100,
        Split.TEST: 200,
    }
    keys = {(item.blueprint.blueprint_id, item.variant_index) for item in allocations}
    assert len(keys) == 1_000


def test_canary_sira_degisiminden_etkilenmez() -> None:
    blueprints = _blueprints()
    first = allocate_canary(blueprints, target=100)
    second = allocate_canary(tuple(reversed(blueprints)), target=100)

    assert [
        (item.blueprint.blueprint_id, item.variant_index) for item in first
    ] == [
        (item.blueprint.blueprint_id, item.variant_index) for item in second
    ]


def test_canary_eksik_split_havuzunu_reddeder() -> None:
    only_train = tuple(
        blueprint for blueprint in _blueprints() if blueprint.split is Split.TRAIN
    )

    with pytest.raises(ValueError, match="validation"):
        allocate_canary(only_train, target=10)


def test_canary_200_katalog_kotalarini_uretimden_once_dengeler(
    repo_root: Path,
) -> None:
    blueprints = load_blueprints(repo_root / "data" / "blueprints")
    initial = allocate_canary(blueprints, target=200)
    split_counts = Counter(
        allocation.blueprint.split.value
        for allocation in initial
        if allocation.blueprint.split is not None
    )
    budget = _canary_budget_config(target=200, split_counts=split_counts)

    balanced = rebalance_canary(
        initial,
        blueprints=blueprints,
        budget=budget,
    )

    decisions = Counter(
        allocation.blueprint.expected_behavior.decision.value
        for allocation in balanced
    )
    kinds = Counter(allocation.blueprint.kind.value for allocation in balanced)
    difficulties = Counter(allocation.blueprint.difficulty for allocation in balanced)
    call_counts = Counter(
        str(len(allocation.blueprint.expected_actions)) for allocation in balanced
    )
    interactions = Counter(
        allocation.blueprint.interaction_type for allocation in balanced
    )
    splits = Counter(
        allocation.blueprint.split.value
        for allocation in balanced
        if allocation.blueprint.split is not None
    )

    assert decisions["direct_answer"] >= 16
    assert 4 <= kinds["empty_result"] <= 16
    assert 10 <= kinds["parallel_tool_call"] <= 18
    assert 16 <= kinds["expected_error"] + kinds["error_recovery"] <= 32
    assert difficulties["medium"] >= 100
    assert 90 <= call_counts["1"] <= 104
    assert 38 <= call_counts["2"] <= 54
    assert 24 <= interactions["multi_turn"] <= 30
    assert splits == {"train": 140, "validation": 20, "test": 40}
    assert len({allocation.blueprint.family_id for allocation in balanced}) == 74


def test_canary_imkansiz_kotayi_api_cagrisindan_once_reddeder() -> None:
    blueprints = _blueprints()
    initial = allocate_canary(blueprints, target=100)
    split_counts = Counter(
        allocation.blueprint.split.value
        for allocation in initial
        if allocation.blueprint.split is not None
    )
    budget = _canary_budget_config(target=100, split_counts=split_counts)

    with pytest.raises(ValueError, match="karşılayamıyor"):
        rebalance_canary(
            initial,
            blueprints=blueprints,
            budget=budget,
        )
