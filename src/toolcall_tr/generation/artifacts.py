"""Release artifact manifesti ve eğitim/eval sınırı."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from toolcall_tr.canonical import sha256_hex

__all__ = [
    "TrainingArtifactPolicyError",
    "build_release_artifact_manifest",
]


class TrainingArtifactPolicyError(ValueError):
    """Bir evaluation dosyası eğitim girdisi olarak işaretlendiğinde yükselir."""


def _label(path: Path, relative_to: Path | None) -> Path:
    if relative_to is None:
        return path
    try:
        return path.resolve().relative_to(relative_to.resolve())
    except ValueError:
        return path


def _is_evaluation_path(path: Path) -> bool:
    return any(part.casefold() == "evaluation" for part in path.parts)


def _metadata(path: Path) -> dict[str, int | str]:
    payload = path.read_bytes()
    return {
        "bytes": len(payload),
        "lines": payload.count(b"\n"),
        "sha256": sha256_hex(payload),
    }


def build_release_artifact_manifest(
    *,
    training_paths: Iterable[Path],
    report_paths: Iterable[Path] = (),
    relative_to: Path | None = None,
) -> dict[str, object]:
    """Eğitim girdilerini raporlardan ayıran release manifesti üret.

    ``evaluation`` ağacındaki hiçbir dosya ``training_paths`` üzerinden
    geçirilemez. Güvenlik eval'leri release paketinde ayrıca dağıtılabilir, fakat
    SFT/finetune girdisi olarak sınıflandırılamaz.
    """

    training = tuple(training_paths)
    reports = tuple(report_paths)
    forbidden = [
        _label(path, relative_to).as_posix()
        for path in training
        if _is_evaluation_path(_label(path, relative_to))
    ]
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise TrainingArtifactPolicyError(
            f"evaluation dosyaları eğitim manifestine alınamaz: {joined}"
        )

    labels: dict[str, str] = {}
    artifacts: dict[str, dict[str, int | str]] = {}
    for artifact_class, paths in (("training", training), ("report", reports)):
        for path in paths:
            label = _label(path, relative_to).as_posix()
            if label in labels:
                raise ValueError(f"artifact birden fazla sınıfta listelendi: {label}")
            labels[label] = artifact_class
            artifacts[label] = _metadata(path)

    return {
        "schema_version": 2,
        "artifacts": dict(sorted(artifacts.items())),
        "artifact_classes": dict(sorted(labels.items())),
        "training_inputs": sorted(
            label for label, artifact_class in labels.items() if artifact_class == "training"
        ),
        "report_inputs": sorted(
            label for label, artifact_class in labels.items() if artifact_class == "report"
        ),
        "policy": {
            "evaluation_as_training": "forbidden",
        },
    }
