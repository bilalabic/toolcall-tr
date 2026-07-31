"""Split'ler arası gerçek genelleme holdout denetimleri.

Family-disjoint split, aynı niyet ailesinin eğitim ve testte görünmesini engeller.
Bu modül buna ek olarak modele sunulan tool şemalarının ve sağlayıcıların train ile
test arasında kesişip kesişmediğini ölçer. Varsayılan ``standard`` profil yalnız
family ayrıklığını zorlar; mevcut korpus davranışını değiştirmez.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from toolcall_tr.models import Example, Split

__all__ = [
    "GeneralizationHoldoutConfig",
    "HoldoutProfile",
    "build_generalization_report",
]

HoldoutProfile = Literal["standard", "unseen_tool", "unseen_provider"]


class GeneralizationHoldoutConfig(BaseModel):
    """Train/test ayrıklığı için uygulanacak kural profili."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: HoldoutProfile = "standard"
    train_split: Split = Split.TRAIN
    evaluation_split: Split = Split.TEST


class _Inventory(TypedDict):
    examples: int
    families: list[str]
    tools: list[str]
    providers: list[str]


def _inventory(examples: Iterable[Example]) -> _Inventory:
    materialized = tuple(examples)
    return {
        "examples": len(materialized),
        "families": sorted({example.family_id for example in materialized}),
        # Holdout, yalnız çağrılan tool'u değil modele gösterilen tüm şemaları
        # ölçer. Aksi hâlde direct-answer negatifleri test tool'unu train'de
        # sızdırabilir.
        "tools": sorted(
            {tool.tool_id for example in materialized for tool in example.tools}
        ),
        "providers": sorted(
            {example.provider for example in materialized}
            | {tool.provider for example in materialized for tool in example.tools}
        ),
    }


def build_generalization_report(
    examples: Iterable[Example],
    config: GeneralizationHoldoutConfig | None = None,
) -> dict[str, object]:
    """Deterministik train/test tool ve provider kesişim raporu üret."""

    resolved = config or GeneralizationHoldoutConfig()
    materialized = tuple(examples)
    train = tuple(
        example for example in materialized if example.split is resolved.train_split
    )
    evaluation = tuple(
        example
        for example in materialized
        if example.split is resolved.evaluation_split
    )
    train_inventory = _inventory(train)
    evaluation_inventory = _inventory(evaluation)

    family_overlap = sorted(
        set(train_inventory["families"]) & set(evaluation_inventory["families"])
    )
    tool_overlap = sorted(
        set(train_inventory["tools"]) & set(evaluation_inventory["tools"])
    )
    provider_overlap = sorted(
        set(train_inventory["providers"]) & set(evaluation_inventory["providers"])
    )

    violations: list[dict[str, object]] = []
    if resolved.profile != "standard":
        if not train:
            violations.append(
                {
                    "code": "holdout_train_split_empty",
                    "split": resolved.train_split.value,
                }
            )
        if not evaluation:
            violations.append(
                {
                    "code": "holdout_evaluation_split_empty",
                    "split": resolved.evaluation_split.value,
                }
            )
    if family_overlap:
        violations.append(
            {
                "code": "family_holdout_overlap",
                "count": len(family_overlap),
                "values": family_overlap,
            }
        )
    if resolved.profile == "unseen_tool" and tool_overlap:
        violations.append(
            {
                "code": "unseen_tool_overlap",
                "count": len(tool_overlap),
                "values": tool_overlap,
            }
        )
    if resolved.profile == "unseen_provider" and provider_overlap:
        violations.append(
            {
                "code": "unseen_provider_overlap",
                "count": len(provider_overlap),
                "values": provider_overlap,
            }
        )

    return {
        "schema_version": 1,
        "profile": resolved.profile,
        "passed": not violations,
        "splits": {
            "train": resolved.train_split.value,
            "evaluation": resolved.evaluation_split.value,
        },
        "rules": {
            "family_disjoint": True,
            "tool_disjoint": resolved.profile == "unseen_tool",
            "provider_disjoint": resolved.profile == "unseen_provider",
        },
        "train": train_inventory,
        "evaluation": evaluation_inventory,
        "overlap": {
            "families": family_overlap,
            "tools": tool_overlap,
            "providers": provider_overlap,
        },
        "violations": violations,
    }
