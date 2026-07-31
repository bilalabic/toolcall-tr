"""Smoke ve release canary kalite kapıları.

Smoke profili boru hattının yapısal olarak çalıştığını gösterir. Release profili
ise bunun üzerine korpus tekrarlarını ve LLM hakemiyle doğrulanması zorunlu
semantik/politika/dil bayraklarını sert kapı olarak uygular.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from toolcall_tr.models import Example

__all__ = [
    "DUPLICATE_FINDING_CODES",
    "REQUIRED_RELEASE_FLAGS",
    "CanaryProfile",
    "build_canary_gate",
]

CanaryProfile = Literal["smoke", "release"]

DUPLICATE_FINDING_CODES: frozenset[str] = frozenset(
    {"exact_duplicate", "normalized_duplicate", "near_duplicate"}
)
REQUIRED_RELEASE_FLAGS: tuple[str, ...] = (
    "semantic_valid",
    "policy_valid",
    "language_valid",
)


def build_canary_gate(
    *,
    profile: CanaryProfile,
    target: int,
    accepted: Sequence[Example],
    rejected_count: int,
    budget_violations: Sequence[object],
    finding_counts: Mapping[str, int],
    generalization_violations: Sequence[object] = (),
) -> dict[str, Any]:
    """Koşunun smoke başarısını ve release uygunluğunu ayrı ayrı hesapla."""
    smoke_passed = (
        len(accepted) == target
        and rejected_count == 0
        and not budget_violations
        and not generalization_violations
    )
    release_blockers: list[dict[str, object]] = []

    for code in sorted(DUPLICATE_FINDING_CODES):
        count = int(finding_counts.get(code, 0))
        if count:
            release_blockers.append(
                {
                    "code": code,
                    "count": count,
                    "message": "Release korpusunda tekrar bulgusu bulunamaz.",
                }
            )

    for flag in REQUIRED_RELEASE_FLAGS:
        invalid_count = sum(
            getattr(example.verification, flag) is not True for example in accepted
        )
        if invalid_count:
            release_blockers.append(
                {
                    "code": f"{flag}_required",
                    "count": invalid_count,
                    "message": f"Release için verification.{flag} true olmalıdır.",
                }
            )

    release_ready = smoke_passed and not release_blockers
    passed = smoke_passed if profile == "smoke" else release_ready
    return {
        "profile": profile,
        "target": target,
        "accepted": len(accepted),
        "rejected": rejected_count,
        "passed": passed,
        "smoke_passed": smoke_passed,
        "release_ready": release_ready if profile == "release" else False,
        "release_blockers": release_blockers,
        "budget_violations": list(budget_violations),
        "generalization_violations": list(generalization_violations),
    }
