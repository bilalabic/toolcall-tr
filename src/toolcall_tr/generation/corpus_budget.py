"""Korpus dağılımı, bütçe ve split bütünlüğü denetimi.

Bu modül sentez motorundan bağımsızdır: yalnızca üretilmiş canonical
``Example`` kayıtlarını okur. Böylece aynı denetim canary, release candidate ve
nihai korpus üzerinde, üretim yönteminden bağımsız olarak çalıştırılabilir.

Rapor sıralı anahtarlar ve sıralı listeler kullanır. Girdi sırası değişse bile
çıktı değişmez ve doğrudan JSON'a yazılabilir.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from toolcall_tr.models import BlueprintKind, Decision, Example, Split

__all__ = [
    "BudgetDimension",
    "CorpusBudgetConfig",
    "RatioConstraint",
    "build_corpus_budget_report",
]

BudgetDimension = Literal[
    "decision",
    "kind",
    "difficulty",
    "provider",
    "domain",
    "interaction_type",
    "tool_call_count",
    "split",
]

_DIMENSION_ORDER: tuple[BudgetDimension, ...] = (
    "decision",
    "kind",
    "difficulty",
    "provider",
    "domain",
    "interaction_type",
    "tool_call_count",
    "split",
)

_FIXED_CATEGORIES: dict[BudgetDimension, tuple[str, ...]] = {
    "decision": tuple(item.value for item in Decision),
    "kind": tuple(item.value for item in BlueprintKind),
    "difficulty": ("easy", "medium", "hard"),
    "provider": (),
    "domain": (),
    "interaction_type": ("single_turn", "multi_turn"),
    "tool_call_count": (),
    "split": tuple(item.value for item in Split),
}


class RatioConstraint(BaseModel):
    """Bir dağılım kategorisinin kabul edilen kapalı oran aralığı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: float = Field(default=0.0, ge=0.0, le=1.0)
    maximum: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("minimum oran maximum orandan büyük olamaz")
        return self


class CorpusBudgetConfig(BaseModel):
    """Bir korpus sürümünün hedef büyüklüğü ve oran bütçeleri.

    ``enforce_target=False`` ara üretimlerin ilerlemesini raporlarken toplam
    hedef farkının build'i başarısız saymamasını sağlar. Oran ve bütünlük
    ihlalleri her durumda denetlenir.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_total: int = Field(ge=1)
    enforce_target: bool = True
    constraints: dict[BudgetDimension, dict[str, RatioConstraint]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_categories(self) -> Self:
        for dimension, categories in self.constraints.items():
            for category in categories:
                if not category:
                    raise ValueError(f"{dimension}: kategori adı boş olamaz")
                if dimension == "tool_call_count" and (
                    not category.isdecimal() or str(int(category)) != category
                ):
                    raise ValueError(
                        "tool_call_count kategorileri negatif olmayan canonical "
                        f"tam sayı olmalı: {category!r}"
                    )
        return self


def _category_for(example: Example, dimension: BudgetDimension) -> str:
    if dimension == "decision":
        return example.scenario.decision.value
    if dimension == "kind":
        return example.scenario.kind.value
    if dimension == "difficulty":
        return example.scenario.difficulty
    if dimension == "provider":
        return example.provider
    if dimension == "domain":
        return example.domain
    if dimension == "interaction_type":
        return example.scenario.interaction_type
    if dimension == "tool_call_count":
        return str(len(example.ground_truth.calls))
    return example.split.value


def _distribution(
    examples: tuple[Example, ...],
    config: CorpusBudgetConfig,
    dimension: BudgetDimension,
) -> dict[str, dict[str, int | float]]:
    counts = Counter(_category_for(example, dimension) for example in examples)
    configured = config.constraints.get(dimension, {})
    categories = sorted(set(counts) | set(configured) | set(_FIXED_CATEGORIES[dimension]))
    total = len(examples)
    return {
        category: {
            "count": counts[category],
            "ratio": counts[category] / total if total else 0.0,
        }
        for category in categories
    }


def _budget(config: CorpusBudgetConfig) -> dict[str, dict[str, dict[str, int | float]]]:
    result: dict[str, dict[str, dict[str, int | float]]] = {}
    for dimension in _DIMENSION_ORDER:
        categories = config.constraints.get(dimension)
        if not categories:
            continue
        result[dimension] = {
            category: {
                "minimum_ratio": constraint.minimum,
                "maximum_ratio": constraint.maximum,
                "minimum_count_at_target": math.ceil(
                    constraint.minimum * config.target_total
                ),
                "maximum_count_at_target": math.floor(
                    constraint.maximum * config.target_total
                ),
            }
            for category, constraint in sorted(categories.items())
        }
    return result


def _integrity(
    examples: tuple[Example, ...],
) -> tuple[list[dict[str, int | str]], list[dict[str, object]]]:
    id_counts = Counter(example.id for example in examples)
    duplicate_ids: list[dict[str, int | str]] = [
        {"id": example_id, "count": count}
        for example_id, count in sorted(id_counts.items())
        if count > 1
    ]

    family_splits: dict[str, set[str]] = defaultdict(set)
    for example in examples:
        family_splits[example.family_id].add(example.split.value)
    family_split_leaks: list[dict[str, object]] = [
        {"family_id": family_id, "splits": sorted(splits)}
        for family_id, splits in sorted(family_splits.items())
        if len(splits) > 1
    ]
    return duplicate_ids, family_split_leaks


def build_corpus_budget_report(
    examples: Iterable[Example],
    config: CorpusBudgetConfig,
) -> dict[str, object]:
    """Deterministik, JSON-serializable korpus bütçe raporu üretir."""

    materialized = tuple(examples)
    total = len(materialized)
    distributions = {
        dimension: _distribution(materialized, config, dimension)
        for dimension in _DIMENSION_ORDER
    }
    duplicate_ids, family_split_leaks = _integrity(materialized)

    violations: list[dict[str, object]] = []
    if config.enforce_target and total != config.target_total:
        violations.append(
            {
                "code": "total_target_mismatch",
                "actual_count": total,
                "target_count": config.target_total,
            }
        )

    for duplicate in duplicate_ids:
        violations.append({"code": "duplicate_id", **duplicate})
    for leak in family_split_leaks:
        violations.append({"code": "family_split_leak", **leak})

    for dimension in _DIMENSION_ORDER:
        for category, constraint in sorted(config.constraints.get(dimension, {}).items()):
            actual = distributions[dimension][category]
            ratio = float(actual["ratio"])
            if ratio < constraint.minimum:
                violations.append(
                    {
                        "code": "ratio_below_minimum",
                        "dimension": dimension,
                        "category": category,
                        "actual_count": actual["count"],
                        "actual_ratio": ratio,
                        "minimum_ratio": constraint.minimum,
                    }
                )
            if ratio > constraint.maximum:
                violations.append(
                    {
                        "code": "ratio_above_maximum",
                        "dimension": dimension,
                        "category": category,
                        "actual_count": actual["count"],
                        "actual_ratio": ratio,
                        "maximum_ratio": constraint.maximum,
                    }
                )

    return {
        "schema_version": 1,
        "passed": not violations,
        "target": {
            "examples": config.target_total,
            "enforced": config.enforce_target,
        },
        "actual": {
            "examples": total,
            "target_delta": total - config.target_total,
            "families": len({example.family_id for example in materialized}),
        },
        "distributions": distributions,
        "budget": _budget(config),
        "integrity": {
            "duplicate_ids": duplicate_ids,
            "family_split_leaks": family_split_leaks,
        },
        "violations": violations,
    }
