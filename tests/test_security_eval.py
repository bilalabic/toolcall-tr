"""Eğitime kapalı sentetik tool-output injection eval sözleşmesi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from toolcall_tr.generation.security_eval import (
    build_security_evaluation_report,
    load_security_evaluations,
)
from toolcall_tr.models import ToolOutputInjectionEval


def test_security_fixture_seti_dogrulanir(repo_root: Path) -> None:
    records = load_security_evaluations(repo_root / "data" / "evaluation" / "security")

    assert len(records) >= 4
    assert len({record.id for record in records}) == len(records)
    assert all(record.source == "synthetic" for record in records)
    assert all(record.training_eligible is False for record in records)
    assert all(
        record.expected_behavior.preserve_user_intent
        and record.expected_behavior.treat_tool_output_as_untrusted_data
        for record in records
    )
    assert all(
        record.expected_behavior.forbidden_tool_calls for record in records
    )

    report = build_security_evaluation_report(records)
    assert report == {
        "schema_version": 1,
        "passed": True,
        "examples": len(records),
        "categories": {"tool_output_prompt_injection": len(records)},
        "actions": {
            "ignore_tool_output_instruction_and_continue_user_goal": len(records)
        },
        "training_eligible": 0,
        "synthetic": len(records),
    }


def test_security_eval_training_eligible_true_olamaz(repo_root: Path) -> None:
    fixture = repo_root / "data" / "evaluation" / "security"
    payload = json.loads(
        (fixture / "tool_output_prompt_injection.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    payload["training_eligible"] = True

    with pytest.raises(ValidationError):
        ToolOutputInjectionEval.model_validate(payload)


def test_injection_arac_ciktisinda_birebir_bulunmali(repo_root: Path) -> None:
    fixture = repo_root / "data" / "evaluation" / "security"
    payload = json.loads(
        (fixture / "tool_output_prompt_injection.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    payload["injected_instruction_tr"] = "Araç çıktısında bulunmayan talimat."

    with pytest.raises(
        ValidationError,
        match="araç çıktısında birebir bulunmalı",
    ):
        ToolOutputInjectionEval.model_validate(payload)
