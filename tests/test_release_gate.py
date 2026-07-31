"""Smoke ve release canary kapısının birbirine karışmadığını doğrular."""

from __future__ import annotations

from typer.testing import CliRunner

from tests.factories import make_example
from toolcall_tr.cli.main import app
from toolcall_tr.generation.release_gate import build_canary_gate


def test_smoke_yapisal_kosuyu_gecirir_ama_release_ready_degil() -> None:
    example = make_example()
    gate = build_canary_gate(
        profile="smoke",
        target=1,
        accepted=(example,),
        rejected_count=0,
        budget_violations=(),
        finding_counts={},
    )

    assert gate["passed"] is True
    assert gate["smoke_passed"] is True
    assert gate["release_ready"] is False
    assert {item["code"] for item in gate["release_blockers"]} == {
        "language_valid_required",
        "policy_valid_required",
        "semantic_valid_required",
    }


def test_release_null_verification_ve_tekrarla_gecemez() -> None:
    gate = build_canary_gate(
        profile="release",
        target=1,
        accepted=(make_example(),),
        rejected_count=0,
        budget_violations=(),
        finding_counts={"near_duplicate": 1},
    )

    assert gate["smoke_passed"] is True
    assert gate["release_ready"] is False
    assert gate["passed"] is False
    assert {item["code"] for item in gate["release_blockers"]} == {
        "language_valid_required",
        "near_duplicate",
        "policy_valid_required",
        "semantic_valid_required",
    }


def test_release_tum_zorunlu_bayraklar_true_ise_gecer() -> None:
    example = make_example()
    example = example.model_copy(
        update={
            "verification": example.verification.model_copy(
                update={
                    "semantic_valid": True,
                    "policy_valid": True,
                    "language_valid": True,
                }
            )
        }
    )
    gate = build_canary_gate(
        profile="release",
        target=1,
        accepted=(example,),
        rejected_count=0,
        budget_violations=(),
        finding_counts={},
    )

    assert gate["passed"] is True
    assert gate["release_ready"] is True
    assert gate["release_blockers"] == []


def test_holdout_ihlali_smoke_kapisini_da_kapatir() -> None:
    gate = build_canary_gate(
        profile="smoke",
        target=1,
        accepted=(make_example(),),
        rejected_count=0,
        budget_violations=(),
        finding_counts={},
        generalization_violations=(
            {
                "code": "unseen_tool_overlap",
                "count": 1,
                "values": ["izmir.search_datasets"],
            },
        ),
    )

    assert gate["smoke_passed"] is False
    assert gate["passed"] is False
    assert gate["generalization_violations"][0]["code"] == "unseen_tool_overlap"


def test_release_profili_hakemsiz_baslamaz() -> None:
    result = CliRunner().invoke(
        app,
        ["generate-canary", "--profile", "release", "--no-judge"],
    )

    assert result.exit_code == 2
    assert "Release profili --judge gerektirir" in result.output


def test_max_candidates_hedeften_kucuk_olamaz() -> None:
    result = CliRunner().invoke(
        app,
        [
            "generate-canary",
            "--profile",
            "smoke",
            "--target",
            "10",
            "--max-candidates",
            "9",
        ],
    )

    assert result.exit_code == 2
    assert "--max-candidates hedef örnek sayısından küçük olamaz" in result.output
