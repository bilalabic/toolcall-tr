"""Security eval fixture yükleme ve kapsama raporu."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from toolcall_tr.models import ToolOutputInjectionEval

__all__ = [
    "build_security_evaluation_report",
    "load_security_evaluations",
]


def load_security_evaluations(directory: Path) -> tuple[ToolOutputInjectionEval, ...]:
    """Bir dizindeki sıralı JSONL security eval kayıtlarını doğrulayarak yükle."""

    records: list[ToolOutputInjectionEval] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                records.append(ToolOutputInjectionEval.model_validate(payload))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: geçersiz security eval: {exc}") from exc

    counts = Counter(record.id for record in records)
    duplicate_ids = sorted(record_id for record_id, count in counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"yinelenen security eval id: {duplicate_ids}")
    return tuple(records)


def build_security_evaluation_report(
    records: tuple[ToolOutputInjectionEval, ...],
) -> dict[str, object]:
    """Eval setinin eğitime kapalı olduğunu ve davranış kapsamını raporla."""

    return {
        "schema_version": 1,
        "passed": bool(records) and all(not record.training_eligible for record in records),
        "examples": len(records),
        "categories": dict(sorted(Counter(record.category for record in records).items())),
        "actions": dict(
            sorted(
                Counter(
                    record.expected_behavior.action for record in records
                ).items()
            )
        ),
        "training_eligible": 0,
        "synthetic": sum(record.source == "synthetic" for record in records),
    }
