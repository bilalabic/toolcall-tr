from __future__ import annotations

from pathlib import Path

import pytest

from toolcall_tr.generation.synthesis import (
    compile_catalog,
    compile_template,
    synthesis_catalog_lock,
    synthesis_lock,
)


def test_template_eksenleri_deterministik_derlenir(repo_root: Path) -> None:
    path = repo_root / "data" / "synthesis" / "currency_latest.template.yaml"
    first = compile_template(path)
    second = compile_template(path)
    assert first == second
    assert [bp.blueprint_id for bp in first] == [
        "synth_currency_try_eur",
        "synth_currency_try_usd",
        "synth_currency_try_gbp",
    ]


def test_lock_tum_girdileri_hashler(repo_root: Path) -> None:
    path = repo_root / "data" / "synthesis" / "currency_latest.template.yaml"
    lock = synthesis_lock(path)
    assert lock["blueprint_count"] == 3
    assert lock["template_hash"].startswith("sha256:")
    assert lock["axis_hash"].startswith("sha256:")
    assert lock["lock_hash"].startswith("sha256:")


def test_katalog_dosya_adina_gore_deterministik_derlenir(repo_root: Path) -> None:
    directory = repo_root / "data" / "synthesis"
    first = compile_catalog(directory)
    second = compile_catalog(directory)

    assert first == second
    assert len(first) == 6
    assert [bp.blueprint_id for bp in first[:3]] == [
        "synth_currency_try_eur",
        "synth_currency_try_usd",
        "synth_currency_try_gbp",
    ]


def test_katalog_limiti_deterministik_on_eki_secer(repo_root: Path) -> None:
    directory = repo_root / "data" / "synthesis"
    assert compile_catalog(directory, limit=2) == compile_catalog(directory)[:2]
    assert compile_template(
        directory / "currency_latest.template.yaml",
        limit=1,
    ) == compile_template(directory / "currency_latest.template.yaml")[:1]

    with pytest.raises(ValueError, match="limit"):
        compile_catalog(directory, limit=-1)


def test_katalog_lock_tum_girdileri_hashler(repo_root: Path) -> None:
    directory = repo_root / "data" / "synthesis"
    lock = synthesis_catalog_lock(directory, limit=4)

    assert lock["version"] == 2
    assert lock["template_count"] == 2
    assert lock["catalog_blueprint_count"] == 6
    assert lock["blueprint_count"] == 4
    assert set(lock["inputs"]) == {
        "currency_latest.template.yaml",
        "currency_pairs.json",
        "weather_location_search.template.yaml",
        "weather_locations.json",
    }
    assert all(value.startswith("sha256:") for value in lock["inputs"].values())
    assert lock["lock_hash"].startswith("sha256:")


def test_katalog_sablonlar_arasi_kimlik_cakismasini_reddeder(
    tmp_path: Path,
) -> None:
    axis = '{"value": ["ayni"]}\n'
    template = """
axis_snapshot: axis.json
template:
  blueprint_id: "synth_{value}"
  family_id: "synth_family_{value}"
  domain: test
  kind: successful_tool_call
  provider: test
  user_goal: test
  known_information: {}
  available_tools: [test.run]
  utterances: [test]
  expected_behavior: {decision: tool_call}
  expected_actions:
    - tool: test.run
      arguments: {}
"""
    (tmp_path / "axis.json").write_text(axis, encoding="utf-8")
    (tmp_path / "a.template.yaml").write_text(template, encoding="utf-8")
    (tmp_path / "b.template.yaml").write_text(template, encoding="utf-8")

    with pytest.raises(ValueError, match="yinelenen blueprint_id"):
        compile_catalog(tmp_path)


def test_katalog_sablonlar_arasi_family_cakismasini_reddeder(
    tmp_path: Path,
) -> None:
    (tmp_path / "axis.json").write_text('{"value": ["ayni"]}\n', encoding="utf-8")
    template = """
axis_snapshot: axis.json
template:
  blueprint_id: "PLACEHOLDER_{value}"
  family_id: "synth_same_family"
  domain: test
  kind: successful_tool_call
  provider: test
  user_goal: test
  known_information: {}
  available_tools: [test.run]
  utterances: [test]
  expected_behavior: {decision: tool_call}
  expected_actions:
    - tool: test.run
      arguments: {}
"""
    (tmp_path / "a.template.yaml").write_text(
        template.replace("PLACEHOLDER", "first"),
        encoding="utf-8",
    )
    (tmp_path / "b.template.yaml").write_text(
        template.replace("PLACEHOLDER", "second"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="yinelenen family_id"):
        compile_catalog(tmp_path)


def test_sablon_yinelenen_family_id_reddeder(tmp_path: Path) -> None:
    (tmp_path / "axis.json").write_text(
        '{"value": ["bir", "iki"]}\n',
        encoding="utf-8",
    )
    (tmp_path / "duplicate.template.yaml").write_text(
        """
axis_snapshot: axis.json
template:
  blueprint_id: "synth_{value}"
  family_id: "synth_same_family"
  domain: test
  kind: successful_tool_call
  provider: test
  user_goal: test
  known_information: {}
  available_tools: [test.run]
  utterances: [test]
  expected_behavior: {decision: tool_call}
  expected_actions:
    - tool: test.run
      arguments: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="yinelenen family_id"):
        compile_template(tmp_path / "duplicate.template.yaml")
