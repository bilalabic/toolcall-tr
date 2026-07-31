"""Template + eksen snapshot'ından deterministik blueprint sentezi."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from toolcall_tr.canonical import sha256_hex, sha256_of
from toolcall_tr.models import Blueprint
from toolcall_tr.pipeline.blueprints import parse_blueprint

__all__ = [
    "compile_catalog",
    "compile_template",
    "synthesis_catalog_lock",
    "synthesis_lock",
]


def _fill(value: Any, slots: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        for name, replacement in slots.items():
            if isinstance(replacement, Mapping):
                for child_name, child_value in replacement.items():
                    value = value.replace(
                        "{" + name + "." + str(child_name) + "}",
                        str(child_value),
                    )
            value = value.replace("{" + name + "}", str(replacement))
        return value
    if isinstance(value, list):
        return [_fill(item, slots) for item in value]
    if isinstance(value, Mapping):
        return {key: _fill(item, slots) for key, item in value.items()}
    return value


def _load(path: Path) -> tuple[dict[str, Any], dict[str, list[Any]], Path]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or not isinstance(raw.get("template"), Mapping):
        raise ValueError(f"{path.name}: template eşlemesi zorunlu")
    axis_path = path.parent / str(raw["axis_snapshot"])
    axes = json.loads(axis_path.read_text(encoding="utf-8"))
    if not isinstance(axes, dict) or not all(isinstance(value, list) for value in axes.values()):
        raise ValueError(f"{axis_path.name}: eksenler liste olmalı")
    return dict(raw["template"]), axes, axis_path


def _validate_limit(limit: int | None) -> None:
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit negatif olmayan bir tam sayı veya None olmalı")


def _ensure_unique(blueprints: tuple[Blueprint, ...], *, source: str) -> None:
    for attribute in ("blueprint_id", "family_id"):
        seen: set[str] = set()
        duplicates: set[str] = set()
        for blueprint in blueprints:
            value = str(getattr(blueprint, attribute))
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        if duplicates:
            rendered = ", ".join(sorted(duplicates))
            raise ValueError(f"{source}: yinelenen {attribute}: {rendered}")


def compile_template(path: Path, *, limit: int | None = None) -> tuple[Blueprint, ...]:
    """Tek şablonu eksenlerin kartezyen çarpımıyla kararlı sırada derler."""
    _validate_limit(limit)
    template, axes, _ = _load(path)
    names = sorted(axes)
    products = itertools.product(*(axes[name] for name in names))
    blueprints: list[Blueprint] = []
    for index, values in enumerate(products):
        payload = _fill(template, dict(zip(names, values, strict=True)))
        for key in ("blueprint_id", "family_id"):
            payload[key] = str(payload[key]).lower()
        blueprints.append(parse_blueprint(payload, source=f"{path.name}:{index}"))
    ids = [item.blueprint_id for item in blueprints]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: sentez yinelenen blueprint_id üretti")
    compiled = tuple(blueprints)
    _ensure_unique(compiled, source=path.name)
    return compiled if limit is None else compiled[:limit]


def compile_catalog(directory: Path, *, limit: int | None = None) -> tuple[Blueprint, ...]:
    """Dizindeki tüm ``*.template.yaml`` dosyalarını deterministik derler."""
    _validate_limit(limit)
    paths = sorted(directory.glob("*.template.yaml"), key=lambda item: item.name)
    if not paths:
        raise ValueError(f"{directory}: *.template.yaml bulunamadı")

    compiled = tuple(
        blueprint
        for path in paths
        for blueprint in compile_template(path)
    )
    _ensure_unique(compiled, source=directory.name)
    return compiled if limit is None else compiled[:limit]


def synthesis_lock(path: Path) -> dict[str, Any]:
    _, _, axis_path = _load(path)
    blueprints = compile_template(path)
    payload = {
        "version": 1,
        "template": path.name,
        "template_hash": sha256_hex(path.read_bytes()),
        "axis_snapshot": axis_path.name,
        "axis_hash": sha256_hex(axis_path.read_bytes()),
        "blueprint_count": len(blueprints),
        "blueprint_hashes": {bp.blueprint_id: bp.content_hash() for bp in blueprints},
    }
    payload["lock_hash"] = sha256_of(payload)
    return payload


def synthesis_catalog_lock(
    directory: Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Katalogdaki tüm girdileri ve seçilen blueprint'leri kilitler."""
    _validate_limit(limit)
    paths = sorted(directory.glob("*.template.yaml"), key=lambda item: item.name)
    if not paths:
        raise ValueError(f"{directory}: *.template.yaml bulunamadı")

    all_blueprints = compile_catalog(directory)
    blueprints = all_blueprints if limit is None else all_blueprints[:limit]
    input_hashes: dict[str, str] = {}
    templates: list[dict[str, Any]] = []

    for path in paths:
        _, _, axis_path = _load(path)
        template_blueprints = compile_template(path)
        template_name = path.relative_to(directory).as_posix()
        try:
            axis_name = axis_path.relative_to(directory).as_posix()
        except ValueError:
            axis_name = str(axis_path.resolve())

        template_hash = sha256_hex(path.read_bytes())
        axis_hash = sha256_hex(axis_path.read_bytes())
        input_hashes[template_name] = template_hash
        previous_axis_hash = input_hashes.setdefault(axis_name, axis_hash)
        if previous_axis_hash != axis_hash:
            raise ValueError(f"{axis_name}: aynı girdinin hash değerleri uyuşmuyor")
        templates.append(
            {
                "template": template_name,
                "template_hash": template_hash,
                "axis_snapshot": axis_name,
                "axis_hash": axis_hash,
                "blueprint_count": len(template_blueprints),
            }
        )

    payload: dict[str, Any] = {
        "version": 2,
        "catalog": directory.name,
        "limit": limit,
        "template_count": len(paths),
        "catalog_blueprint_count": len(all_blueprints),
        "blueprint_count": len(blueprints),
        "inputs": dict(sorted(input_hashes.items())),
        "templates": templates,
        "blueprint_hashes": {
            blueprint.blueprint_id: blueprint.content_hash() for blueprint in blueprints
        },
    }
    payload["lock_hash"] = sha256_of(payload)
    return payload
