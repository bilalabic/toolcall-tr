"""Phase 5 korpus bütçesi ve split bütünlüğü denetimi."""

from __future__ import annotations

import json
from collections import Counter
from typing import Literal

import pytest
from pydantic import ValidationError

from tests.factories import make_example, make_provenance
from toolcall_tr.generation.corpus_budget import (
    CorpusBudgetConfig,
    RatioConstraint,
    build_corpus_budget_report,
)
from toolcall_tr.models import (
    BlueprintKind,
    Decision,
    GroundTruth,
    Message,
    MessageRole,
    Scenario,
    Split,
    ToolCallRecord,
)


def _example(
    index: int,
    *,
    family_id: str,
    split: Split,
    provider: str = "izmir_ckan",
    domain: str = "open_data",
    decision: Decision = Decision.TOOL_CALL,
    kind: BlueprintKind = BlueprintKind.SUCCESSFUL_TOOL_CALL,
    difficulty: Literal["easy", "medium", "hard"] = "easy",
    interaction_type: Literal["single_turn", "multi_turn"] = "single_turn",
    call_count: int = 1,
):
    calls = tuple(
        ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"})
        for _ in range(call_count)
    )
    if decision is Decision.TOOL_CALL:
        messages = (
            Message(role=MessageRole.USER, content="Otobüs verisini bul."),
            Message(role=MessageRole.ASSISTANT, tool_calls=calls),
        )
    else:
        calls = ()
        messages = (
            Message(role=MessageRole.USER, content="Merhaba."),
            Message(role=MessageRole.ASSISTANT, content="Merhaba!"),
        )

    return make_example(
        example_id=f"toolcall_tr_open_data_{index:06d}",
        family_id=family_id,
        split=split,
        provider=provider,
        domain=domain,
        scenario=Scenario(
            decision=decision,
            kind=kind,
            interaction_type=interaction_type,
            difficulty=difficulty,
            expected_result="success" if decision is Decision.TOOL_CALL else "no_call",
        ),
        messages=messages,
        ground_truth=GroundTruth(
            calls=calls,
            response_intent_tr="Selamla." if decision is not Decision.TOOL_CALL else None,
            assistant_response_tr=(
                "Merhaba!" if decision is not Decision.TOOL_CALL else None
            ),
        ),
        provenance=make_provenance(family_id=family_id),
    )


def _sample_examples():
    return (
        _example(1, family_id="family_a", split=Split.TRAIN),
        _example(
            2,
            family_id="family_b",
            split=Split.TEST,
            provider="met_norway",
            domain="weather",
            kind=BlueprintKind.SEQUENTIAL_TOOL_CALL,
            difficulty="hard",
            interaction_type="multi_turn",
            call_count=2,
        ),
        _example(
            3,
            family_id="family_c",
            split=Split.VALIDATION,
            decision=Decision.DIRECT_ANSWER,
            kind=BlueprintKind.SHOULD_ANSWER_DIRECTLY,
            difficulty="medium",
            call_count=0,
        ),
    )


def test_report_all_required_distributions() -> None:
    report = build_corpus_budget_report(
        _sample_examples(),
        CorpusBudgetConfig(target_total=3),
    )

    assert report["passed"] is True
    assert report["actual"] == {"examples": 3, "target_delta": 0, "families": 3}
    distributions = report["distributions"]
    assert set(distributions) == {
        "decision",
        "kind",
        "difficulty",
        "provider",
        "domain",
        "interaction_type",
        "tool_call_count",
        "split",
    }
    assert distributions["decision"]["tool_call"] == {
        "count": 2,
        "ratio": pytest.approx(2 / 3),
    }
    assert distributions["kind"]["expected_error"] == {"count": 0, "ratio": 0.0}
    assert distributions["provider"]["izmir_ckan"]["count"] == 2
    assert distributions["domain"]["weather"]["count"] == 1
    assert distributions["interaction_type"]["multi_turn"]["count"] == 1
    assert distributions["tool_call_count"] == {
        "0": {"count": 1, "ratio": pytest.approx(1 / 3)},
        "1": {"count": 1, "ratio": pytest.approx(1 / 3)},
        "2": {"count": 1, "ratio": pytest.approx(1 / 3)},
    }
    assert distributions["split"]["train"]["count"] == 1


def test_ratio_and_total_violations_are_explicit() -> None:
    config = CorpusBudgetConfig(
        target_total=4,
        constraints={
            "decision": {
                "tool_call": RatioConstraint(minimum=0.80),
                "clarification": RatioConstraint(minimum=0.10),
            },
            "provider": {
                "izmir_ckan": RatioConstraint(maximum=0.50),
            },
        },
    )

    report = build_corpus_budget_report(_sample_examples(), config)

    assert report["passed"] is False
    assert report["budget"]["decision"]["tool_call"] == {
        "minimum_ratio": 0.8,
        "maximum_ratio": 1.0,
        "minimum_count_at_target": 4,
        "maximum_count_at_target": 4,
    }
    assert [violation["code"] for violation in report["violations"]] == [
        "total_target_mismatch",
        "ratio_below_minimum",
        "ratio_below_minimum",
        "ratio_above_maximum",
    ]
    assert report["violations"][2]["category"] == "tool_call"
    assert report["violations"][3]["category"] == "izmir_ckan"


def test_ratio_bounds_are_inclusive() -> None:
    config = CorpusBudgetConfig(
        target_total=3,
        constraints={
            "split": {
                "train": RatioConstraint(minimum=1 / 3, maximum=1 / 3),
            }
        },
    )

    report = build_corpus_budget_report(_sample_examples(), config)

    assert report["passed"] is True
    assert report["violations"] == []


def test_integrity_finds_duplicate_id_and_family_split_leak() -> None:
    first = _example(1, family_id="shared_family", split=Split.TRAIN)
    second = _example(2, family_id="shared_family", split=Split.TEST)
    duplicate = _example(1, family_id="other_family", split=Split.TRAIN)

    report = build_corpus_budget_report(
        (first, second, duplicate),
        CorpusBudgetConfig(target_total=3),
    )

    assert report["integrity"] == {
        "duplicate_ids": [{"id": "toolcall_tr_open_data_000001", "count": 2}],
        "family_split_leaks": [
            {"family_id": "shared_family", "splits": ["test", "train"]}
        ],
    }
    assert [violation["code"] for violation in report["violations"]] == [
        "duplicate_id",
        "family_split_leak",
    ]


def test_non_enforced_target_reports_progress_without_violation() -> None:
    report = build_corpus_budget_report(
        _sample_examples(),
        CorpusBudgetConfig(target_total=1_000, enforce_target=False),
    )

    assert report["passed"] is True
    assert report["target"] == {"examples": 1_000, "enforced": False}
    assert report["actual"]["target_delta"] == -997


def test_empty_corpus_has_zero_ratios_and_constraint_violation() -> None:
    config = CorpusBudgetConfig(
        target_total=10,
        enforce_target=False,
        constraints={"domain": {"weather": RatioConstraint(minimum=0.25)}},
    )

    report = build_corpus_budget_report((), config)

    assert report["distributions"]["domain"]["weather"] == {"count": 0, "ratio": 0.0}
    assert report["violations"] == [
        {
            "code": "ratio_below_minimum",
            "dimension": "domain",
            "category": "weather",
            "actual_count": 0,
            "actual_ratio": 0.0,
            "minimum_ratio": 0.25,
        }
    ]


def test_report_is_input_order_independent_and_json_serializable() -> None:
    examples = _sample_examples()
    config = CorpusBudgetConfig(target_total=3)

    forward = build_corpus_budget_report(examples, config)
    reverse = build_corpus_budget_report(reversed(examples), config)

    assert forward == reverse
    payload = json.dumps(forward, sort_keys=True, ensure_ascii=False, allow_nan=False)
    assert json.loads(payload) == forward


@pytest.mark.parametrize(
    "payload",
    [
        {"minimum": 0.8, "maximum": 0.2},
        {"minimum": -0.1},
        {"maximum": 1.1},
    ],
)
def test_invalid_ratio_constraint_is_rejected(payload: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        RatioConstraint(**payload)


@pytest.mark.parametrize("category", ["-1", "01", "1.0", "many"])
def test_invalid_tool_call_count_category_is_rejected(category: str) -> None:
    with pytest.raises(ValidationError):
        CorpusBudgetConfig(
            target_total=10,
            constraints={"tool_call_count": {category: RatioConstraint()}},
        )


def test_canary_smoke_ve_pilot_farkli_tolerans_kullanir() -> None:
    from toolcall_tr.cli.main import _canary_budget_config

    smoke = _canary_budget_config(
        target=100,
        split_counts=Counter({"train": 70, "validation": 10, "test": 20}),
    )
    pilot = _canary_budget_config(
        target=200,
        split_counts=Counter({"train": 140, "validation": 20, "test": 40}),
    )

    assert smoke.constraints["decision"]["cannot_answer"] == RatioConstraint(
        minimum=0.07,
        maximum=0.15,
    )
    assert smoke.constraints["tool_call_count"]["2"] == RatioConstraint(
        minimum=0.17,
        maximum=0.27,
    )
    assert pilot.constraints["decision"] == {
        "tool_call": RatioConstraint(minimum=0.68, maximum=0.72),
        "clarification": RatioConstraint(minimum=0.04, maximum=0.10),
        "direct_answer": RatioConstraint(minimum=0.08, maximum=0.16),
        "cannot_answer": RatioConstraint(minimum=0.07, maximum=0.13),
    }
    assert pilot.constraints["tool_call_count"] == {
        "0": RatioConstraint(minimum=0.28, maximum=0.33),
        "1": RatioConstraint(minimum=0.45, maximum=0.52),
        "2": RatioConstraint(minimum=0.19, maximum=0.27),
        "3": RatioConstraint(minimum=0.01, maximum=0.04),
    }
    assert pilot.constraints["interaction_type"]["multi_turn"] == RatioConstraint(
        minimum=0.12,
        maximum=0.15,
    )
    assert pilot.constraints["kind"]["parallel_tool_call"] == RatioConstraint(
        minimum=0.05,
        maximum=0.09,
    )
