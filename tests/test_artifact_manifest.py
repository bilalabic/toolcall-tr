"""Release artifact sınıflandırması eğitim/eval sızıntısını engeller."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolcall_tr.generation.artifacts import (
    TrainingArtifactPolicyError,
    build_release_artifact_manifest,
)


def test_manifest_training_ve_report_artifactlarini_ayirir(tmp_path: Path) -> None:
    training = tmp_path / "out" / "sft" / "openai.jsonl"
    report = tmp_path / "reports" / "generalization_report.json"
    training.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    training.write_text('{"messages":[]}\n', encoding="utf-8")
    report.write_text('{"passed":true}\n', encoding="utf-8")

    manifest = build_release_artifact_manifest(
        training_paths=(training,),
        report_paths=(report,),
        relative_to=tmp_path,
    )

    assert manifest["schema_version"] == 2
    assert manifest["training_inputs"] == ["out/sft/openai.jsonl"]
    assert manifest["report_inputs"] == ["reports/generalization_report.json"]
    assert manifest["artifact_classes"] == {
        "out/sft/openai.jsonl": "training",
        "reports/generalization_report.json": "report",
    }


def test_security_eval_training_manifestine_alinamaz(tmp_path: Path) -> None:
    security_eval = (
        tmp_path
        / "data"
        / "evaluation"
        / "security"
        / "tool_output_prompt_injection.jsonl"
    )
    security_eval.parent.mkdir(parents=True)
    security_eval.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        TrainingArtifactPolicyError,
        match="evaluation dosyaları eğitim manifestine alınamaz",
    ):
        build_release_artifact_manifest(
            training_paths=(security_eval,),
            relative_to=tmp_path,
        )


def test_security_eval_ayri_rapor_artifacti_olarak_tasinabilir(
    tmp_path: Path,
) -> None:
    security_eval = (
        tmp_path
        / "data"
        / "evaluation"
        / "security"
        / "tool_output_prompt_injection.jsonl"
    )
    security_eval.parent.mkdir(parents=True)
    security_eval.write_text("{}\n", encoding="utf-8")

    manifest = build_release_artifact_manifest(
        training_paths=(),
        report_paths=(security_eval,),
        relative_to=tmp_path,
    )

    assert manifest["training_inputs"] == []
    assert manifest["report_inputs"] == [
        "data/evaluation/security/tool_output_prompt_injection.jsonl"
    ]
