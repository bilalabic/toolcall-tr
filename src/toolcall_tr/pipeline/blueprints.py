"""Blueprint YAML dosyalarının yüklenmesi ve split ataması.

YAML biçimi elle yazılabilir olacak şekilde tasarlanmıştır; yükleyici iki
kısayolu genişletir:

* ``q: "otobüs"`` -> ``LiteralArg(value="otobüs", origin=user_message)``
* ``"$actions[0].result.results[0].name"`` -> ``StepRefArg``

**Split fan-out'tan ÖNCE ve family seviyesinde** atanır. `hash(family_id)`'den
türetildiği için yeni blueprint eklemek mevcut atamaları karıştırmaz ve
paraphrase varyantları yapısal olarak test kümesine sızamaz.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from toolcall_tr.models import (
    ArgOrigin,
    Blueprint,
    ExpectedAction,
    ExpectSpec,
    LiteralArg,
    Split,
    StepRefArg,
)
from toolcall_tr.models.args import ArgValue, parse_step_reference

__all__ = [
    "BlueprintLoadError",
    "assign_split",
    "load_blueprint",
    "load_blueprints",
    "parse_blueprint",
    "split_report",
]


class BlueprintLoadError(ValueError):
    """Blueprint dosyası okunamadı veya geçersiz."""


def _parse_argument(raw: Any) -> ArgValue:
    """Kısayolları genişletir."""
    if isinstance(raw, Mapping):
        if "step_index" in raw:
            return StepRefArg(
                step_index=int(raw["step_index"]),
                path=str(raw["path"]),
                semantic_type=raw.get("semantic_type"),
            )
        origin = ArgOrigin(raw.get("origin", ArgOrigin.USER_MESSAGE.value))
        return LiteralArg(value=raw["value"], origin=origin)

    if isinstance(raw, str):
        reference = parse_step_reference(raw)
        if reference is not None:
            step_index, path = reference
            return StepRefArg(step_index=step_index, path=path)

    return LiteralArg(value=raw, origin=ArgOrigin.USER_MESSAGE)


def _parse_action(raw: Mapping[str, Any]) -> ExpectedAction:
    expect_raw = raw.get("expect")
    expect = ExpectSpec(**expect_raw) if expect_raw else ExpectSpec()
    arguments = {
        name: _parse_argument(value) for name, value in (raw.get("arguments") or {}).items()
    }
    return ExpectedAction(tool_id=str(raw["tool"]), arguments=arguments, expect=expect)


def parse_blueprint(data: Mapping[str, Any], *, source: str = "<mapping>") -> Blueprint:
    """Ayrıştırılmış blueprint eşlemesini canonical modele çevirir."""
    if not isinstance(data, Mapping):
        raise BlueprintLoadError(f"{source}: kök nesne bir eşleme olmalı")

    payload = dict(data)
    payload["expected_actions"] = tuple(
        _parse_action(action) for action in payload.get("expected_actions") or ()
    )
    for key in ("available_tools", "utterances", "missing_information"):
        if key in payload and payload[key] is not None:
            payload[key] = tuple(payload[key])

    try:
        return Blueprint(**payload)
    except (TypeError, ValueError) as exc:
        raise BlueprintLoadError(f"{source}: {exc}") from exc


def load_blueprint(path: Path) -> Blueprint:
    """Tek bir YAML dosyasını `Blueprint`'e çevirir."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BlueprintLoadError(f"{path.name}: YAML ayrıştırılamadı: {exc}") from exc
    if not isinstance(data, Mapping):
        raise BlueprintLoadError(f"{path.name}: kök nesne bir eşleme olmalı")
    return parse_blueprint(data, source=path.name)


def load_blueprints(directory: Path, *, assign_splits: bool = True) -> tuple[Blueprint, ...]:
    """Dizindeki tüm blueprint'leri **dosya adına göre sıralı** yükler.

    Sıralama determinizm içindir: dizin listeleme sırası platforma göre değişir.
    """
    paths = sorted(directory.glob("*.yaml"))
    blueprints = [load_blueprint(path) for path in paths]

    seen: set[str] = set()
    for blueprint in blueprints:
        if blueprint.blueprint_id in seen:
            raise BlueprintLoadError(f"yinelenen blueprint_id: {blueprint.blueprint_id}")
        seen.add(blueprint.blueprint_id)

    if not assign_splits:
        return tuple(blueprints)

    return tuple(
        blueprint.model_copy(update={"split": blueprint.split or assign_split(blueprint.family_id)})
        for blueprint in blueprints
    )


def assign_split(
    family_id: str,
    *,
    train_ratio: float = 0.70,
    validation_ratio: float = 0.10,
) -> Split:
    """`family_id`'den deterministik split ataması.

    Hash tabanlıdır, sıralı sayaç değil: yeni bir family eklemek mevcutların
    atamasını **değiştirmez**. Sayaç kullanılsaydı listeye bir blueprint
    eklemek tüm bölmeyi kaydırırdı.
    """
    digest = hashlib.sha256(f"split:{family_id}".encode()).digest()
    position = int.from_bytes(digest[:8], "big") / float(1 << 64)

    if position < train_ratio:
        return Split.TRAIN
    if position < train_ratio + validation_ratio:
        return Split.VALIDATION
    return Split.TEST


def split_report(blueprints: Iterable[Blueprint]) -> dict[str, Any]:
    """Bölme dağılımı ve sızıntı kontrolü.

    Bir `family_id` birden fazla split'te görünüyorsa benchmark kirlenmiştir.
    """
    families: dict[str, set[str]] = {}
    counts: dict[str, int] = {split.value: 0 for split in Split}

    for blueprint in blueprints:
        split = blueprint.split
        if split is None:
            continue
        counts[split.value] += 1
        families.setdefault(blueprint.family_id, set()).add(split.value)

    leaked = sorted(family for family, splits in families.items() if len(splits) > 1)
    return {
        "counts": counts,
        "family_count": len(families),
        "leaked_families": leaked,
    }
