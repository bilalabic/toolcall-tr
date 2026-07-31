"""Family, tool ve provider holdout profilleri."""

from __future__ import annotations

from tests.factories import make_example, make_provenance, make_tool
from toolcall_tr.generation.generalization import (
    GeneralizationHoldoutConfig,
    build_generalization_report,
)
from toolcall_tr.models import Split


def _example(
    index: int,
    *,
    split: Split,
    family_id: str,
    namespace: str,
    provider: str,
):
    return make_example(
        example_id=f"toolcall_tr_open_data_{index:06d}",
        split=split,
        family_id=family_id,
        provider=provider,
        provenance=make_provenance(family_id=family_id),
        tools=(
            make_tool(
                tool_id=f"{namespace}.search_datasets",
                provider=provider,
            ),
        ),
    )


def test_standard_profile_reports_overlap_without_changing_default_gate() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="train_family",
            namespace="shared",
            provider="shared_provider",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="test_family",
            namespace="shared",
            provider="shared_provider",
        ),
    )

    report = build_generalization_report(examples)

    assert report["profile"] == "standard"
    assert report["passed"] is True
    assert report["rules"] == {
        "family_disjoint": True,
        "tool_disjoint": False,
        "provider_disjoint": False,
    }
    assert report["overlap"] == {
        "families": [],
        "tools": ["shared.search_datasets"],
        "providers": ["shared_provider"],
    }


def test_unseen_tool_profile_rejects_train_test_tool_overlap() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="train_family",
            namespace="shared",
            provider="provider_a",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="test_family",
            namespace="shared",
            provider="provider_b",
        ),
    )

    report = build_generalization_report(
        examples,
        GeneralizationHoldoutConfig(profile="unseen_tool"),
    )

    assert report["passed"] is False
    assert report["violations"] == [
        {
            "code": "unseen_tool_overlap",
            "count": 1,
            "values": ["shared.search_datasets"],
        }
    ]


def test_unseen_tool_allows_seen_provider_when_tool_schemas_are_disjoint() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="train_family",
            namespace="train_tool",
            provider="shared_provider",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="test_family",
            namespace="test_tool",
            provider="shared_provider",
        ),
    )

    report = build_generalization_report(
        examples,
        GeneralizationHoldoutConfig(profile="unseen_tool"),
    )

    assert report["passed"] is True
    assert report["overlap"]["tools"] == []
    assert report["overlap"]["providers"] == ["shared_provider"]


def test_unseen_provider_rejects_provider_overlap_and_reports_tool_overlap() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="train_family",
            namespace="train_tool",
            provider="shared_provider",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="test_family",
            namespace="test_tool",
            provider="shared_provider",
        ),
    )

    report = build_generalization_report(
        examples,
        GeneralizationHoldoutConfig(profile="unseen_provider"),
    )

    assert report["passed"] is False
    assert report["violations"][0]["code"] == "unseen_provider_overlap"
    assert report["overlap"]["tools"] == []


def test_family_disjoint_rule_remains_active_for_every_profile() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="leaked_family",
            namespace="train_tool",
            provider="provider_a",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="leaked_family",
            namespace="test_tool",
            provider="provider_b",
        ),
    )

    report = build_generalization_report(examples)

    assert report["passed"] is False
    assert report["violations"] == [
        {
            "code": "family_holdout_overlap",
            "count": 1,
            "values": ["leaked_family"],
        }
    ]


def test_report_is_input_order_independent() -> None:
    examples = (
        _example(
            1,
            split=Split.TRAIN,
            family_id="train_family",
            namespace="train_tool",
            provider="provider_a",
        ),
        _example(
            2,
            split=Split.TEST,
            family_id="test_family",
            namespace="test_tool",
            provider="provider_b",
        ),
    )
    config = GeneralizationHoldoutConfig(profile="unseen_provider")

    assert build_generalization_report(examples, config) == build_generalization_report(
        reversed(examples),
        config,
    )


def test_holdout_profile_empty_evaluation_split_ile_gecemez() -> None:
    report = build_generalization_report(
        (
            _example(
                1,
                split=Split.TRAIN,
                family_id="train_family",
                namespace="train_tool",
                provider="provider_a",
            ),
        ),
        GeneralizationHoldoutConfig(profile="unseen_tool"),
    )

    assert report["passed"] is False
    assert report["violations"] == [
        {
            "code": "holdout_evaluation_split_empty",
            "split": "test",
        }
    ]
