"""Deterministik canary örnekleme planı.

Canary, doğrulanmış blueprint'leri yeniden çalıştırır ve her biri için farklı
Türkçe ifade varyantları üretir. Bölme bütçesi örnek üretiminden *önce*
hesaplanır; böylece train/validation/test oranları sonradan dosya keserek
oluşturulmaz ve family sızıntısı riski doğmaz.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from toolcall_tr.generation.corpus_budget import BudgetDimension, CorpusBudgetConfig
from toolcall_tr.models import Blueprint, Split

__all__ = ["CanaryAllocation", "allocate_canary", "rebalance_canary"]


@dataclass(frozen=True, slots=True)
class CanaryAllocation:
    """Tek bir blueprint/varyant çalıştırması."""

    blueprint: Blueprint
    variant_index: int


def allocate_canary(
    blueprints: Sequence[Blueprint],
    *,
    target: int,
    split_targets: Mapping[Split, int] | None = None,
) -> tuple[CanaryAllocation, ...]:
    """Hedef boyuta göre dengeli, deterministik çalıştırma listesi oluştur.

    Her split içindeki blueprint'ler kimliğe göre sıralanır ve round-robin
    dolaşılır. Böylece tek bir kolay senaryo bütçeyi dolduramaz. Her
    ``(blueprint_id, variant_index)`` çifti benzersizdir.
    """
    if target <= 0:
        raise ValueError("canary hedefi pozitif olmalı")
    if not blueprints:
        raise ValueError("canary için en az bir blueprint gerekli")
    if any(blueprint.split is None for blueprint in blueprints):
        raise ValueError("canary öncesinde tüm blueprint split'leri atanmalı")

    targets = dict(split_targets or _default_split_targets(target))
    if set(targets) != set(Split):
        raise ValueError("split_targets train, validation ve test anahtarlarını içermeli")
    if any(value < 0 for value in targets.values()):
        raise ValueError("split hedefleri negatif olamaz")
    if sum(targets.values()) != target:
        raise ValueError("split hedeflerinin toplamı canary hedefine eşit olmalı")

    by_split: dict[Split, list[Blueprint]] = defaultdict(list)
    for blueprint in blueprints:
        assert blueprint.split is not None
        by_split[blueprint.split].append(blueprint)
    for items in by_split.values():
        items.sort(key=lambda item: item.blueprint_id)

    allocations: list[CanaryAllocation] = []
    for split in Split:
        split_target = targets[split]
        candidates = by_split.get(split, [])
        if split_target and not candidates:
            raise ValueError(f"{split.value} için hedef var ancak blueprint yok")

        per_blueprint: dict[str, int] = defaultdict(int)
        for position in range(split_target):
            blueprint = candidates[position % len(candidates)]
            variant_index = per_blueprint[blueprint.blueprint_id]
            per_blueprint[blueprint.blueprint_id] += 1
            allocations.append(
                CanaryAllocation(blueprint=blueprint, variant_index=variant_index)
            )

    return tuple(allocations)


def rebalance_canary(
    allocations: Sequence[CanaryAllocation],
    *,
    blueprints: Sequence[Blueprint],
    budget: CorpusBudgetConfig,
) -> tuple[CanaryAllocation, ...]:
    """Kota ihlallerini API çağrısından önce deterministik olarak gider.

    Başlangıçtaki round-robin plan aile kapsamını ve split hedeflerini korur.
    Bu fonksiyon yalnızca aynı split içindeki blueprint'leri değiştirerek karar,
    senaryo türü, zorluk ve tool çağrısı sayısı bütçelerini karşılar. Böylece
    doğal dil üreticisinin rastgele çıktısı korpus kompozisyonunu belirlemez.
    """
    if len(allocations) != budget.target_total:
        raise ValueError("canary tahsis sayısı korpus bütçesi hedefiyle aynı olmalı")
    if not allocations:
        return ()

    ordered_blueprints = tuple(sorted(blueprints, key=lambda item: item.blueprint_id))
    by_split: dict[Split, tuple[Blueprint, ...]] = {
        split: tuple(
            blueprint for blueprint in ordered_blueprints if blueprint.split is split
        )
        for split in Split
    }
    selected = [allocation.blueprint for allocation in allocations]
    blueprint_counts = Counter(item.blueprint_id for item in selected)
    counts = _allocation_counts(selected, budget)
    current_penalty = _budget_penalty(counts, budget)

    # Her başarılı takas cezayı en az bir azaltır; bu sınır bozuk bir
    # konfigürasyonda sonsuz döngüyü ayrıca engeller.
    for _ in range(budget.target_total * max(1, len(ordered_blueprints))):
        if current_penalty == 0:
            break

        best: tuple[
            tuple[int, int, int, str],
            int,
            Blueprint,
            dict[tuple[BudgetDimension, str], int],
        ] | None = None
        for index, current in enumerate(selected):
            # Her family en az bir kez korpusta kalsın.
            if blueprint_counts[current.blueprint_id] <= 1:
                continue
            assert current.split is not None
            for candidate in by_split[current.split]:
                if candidate.blueprint_id == current.blueprint_id:
                    continue
                candidate_counts = _counts_after_swap(
                    counts,
                    current=current,
                    candidate=candidate,
                    budget=budget,
                )
                penalty = _budget_penalty(candidate_counts, budget)
                if penalty >= current_penalty:
                    continue

                # Eşit kalite artışlarında az kullanılan blueprint'i seç.
                balance = blueprint_counts[candidate.blueprint_id] - blueprint_counts[
                    current.blueprint_id
                ]
                key = (penalty, balance, index, candidate.blueprint_id)
                if best is None or key < best[0]:
                    best = (key, index, candidate, candidate_counts)

        if best is None:
            break

        _, index, candidate, counts = best
        current = selected[index]
        blueprint_counts[current.blueprint_id] -= 1
        blueprint_counts[candidate.blueprint_id] += 1
        selected[index] = candidate
        current_penalty = _budget_penalty(counts, budget)

    if current_penalty:
        raise ValueError(
            "blueprint kataloğu istenen canary dağılımını karşılayamıyor: "
            + ", ".join(_budget_deficits(counts, budget))
        )

    variants: Counter[str] = Counter()
    result: list[CanaryAllocation] = []
    for blueprint in selected:
        variant_index = variants[blueprint.blueprint_id]
        variants[blueprint.blueprint_id] += 1
        result.append(
            CanaryAllocation(blueprint=blueprint, variant_index=variant_index)
        )
    return tuple(result)


def _category_for_blueprint(
    blueprint: Blueprint,
    dimension: BudgetDimension,
) -> str:
    if dimension == "decision":
        return blueprint.expected_behavior.decision.value
    if dimension == "kind":
        return blueprint.kind.value
    if dimension == "difficulty":
        return blueprint.difficulty
    if dimension == "provider":
        return blueprint.provider
    if dimension == "domain":
        return blueprint.domain
    if dimension == "interaction_type":
        return blueprint.interaction_type
    if dimension == "tool_call_count":
        return str(len(blueprint.expected_actions))
    assert blueprint.split is not None
    return blueprint.split.value


def _allocation_counts(
    blueprints: Sequence[Blueprint],
    budget: CorpusBudgetConfig,
) -> dict[tuple[BudgetDimension, str], int]:
    counts: Counter[tuple[BudgetDimension, str]] = Counter()
    for blueprint in blueprints:
        for dimension in budget.constraints:
            counts[(dimension, _category_for_blueprint(blueprint, dimension))] += 1
    return dict(counts)


def _counts_after_swap(
    counts: dict[tuple[BudgetDimension, str], int],
    *,
    current: Blueprint,
    candidate: Blueprint,
    budget: CorpusBudgetConfig,
) -> dict[tuple[BudgetDimension, str], int]:
    updated = dict(counts)
    for dimension in budget.constraints:
        old_category = _category_for_blueprint(current, dimension)
        new_category = _category_for_blueprint(candidate, dimension)
        if old_category == new_category:
            continue
        old_key = (dimension, old_category)
        new_key = (dimension, new_category)
        updated[old_key] = updated.get(old_key, 0) - 1
        updated[new_key] = updated.get(new_key, 0) + 1
    return updated


def _budget_penalty(
    counts: Mapping[tuple[BudgetDimension, str], int],
    budget: CorpusBudgetConfig,
) -> int:
    penalty = 0
    for dimension, categories in budget.constraints.items():
        for category, constraint in categories.items():
            count = counts.get((dimension, category), 0)
            minimum = math.ceil(constraint.minimum * budget.target_total)
            maximum = math.floor(constraint.maximum * budget.target_total)
            if count < minimum:
                penalty += (minimum - count) ** 2
            elif count > maximum:
                penalty += (count - maximum) ** 2
    return penalty


def _budget_deficits(
    counts: Mapping[tuple[BudgetDimension, str], int],
    budget: CorpusBudgetConfig,
) -> list[str]:
    deficits: list[str] = []
    for dimension, categories in budget.constraints.items():
        for category, constraint in categories.items():
            count = counts.get((dimension, category), 0)
            minimum = math.ceil(constraint.minimum * budget.target_total)
            maximum = math.floor(constraint.maximum * budget.target_total)
            if count < minimum:
                deficits.append(f"{dimension}/{category}={count}<{minimum}")
            elif count > maximum:
                deficits.append(f"{dimension}/{category}={count}>{maximum}")
    return sorted(deficits)


def _default_split_targets(target: int) -> dict[Split, int]:
    """70/10/20 hedefini, yuvarlama artığını train'e vererek tam sayıya çevir."""
    validation = target // 10
    test = target // 5
    train = target - validation - test
    return {
        Split.TRAIN: train,
        Split.VALIDATION: validation,
        Split.TEST: test,
    }
