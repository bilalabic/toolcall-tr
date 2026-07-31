"""Uçtan uca boru hattı — depodaki **gerçek** korpus üzerinde.

Bu dosya planın "Doğrulama" bölümünün makine tarafından çalıştırılan hâlidir.
Tek bir soru sorar: *depodaki blueprint'ler, cassette'ler ve snapshot'larla,
ağ olmadan, yeniden üretilebilir ve doğrulanmış örnekler üretilebiliyor mu?*
"""

from __future__ import annotations

import json
import re
import socket
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from toolcall_tr.generation import TemplateQueryGenerator, allocate_canary, rebalance_canary
from toolcall_tr.groundtruth.planner import try_plan
from toolcall_tr.groundtruth.runner import Environment, run
from toolcall_tr.models import (
    Blueprint,
    Decision,
    Example,
    ExecutionClass,
    MessageRole,
    Split,
)
from toolcall_tr.pipeline.assemble import assemble_example, example_id
from toolcall_tr.pipeline.blueprints import assign_split, load_blueprints, split_report
from toolcall_tr.pipeline.environment import build_default_registry, open_default_environment
from toolcall_tr.serialize import to_canonical_jsonl
from toolcall_tr.validation import ValidationSubject, build_default_pipeline

CREATED_AT = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def blueprints(repo_root: Path) -> tuple[Blueprint, ...]:
    return load_blueprints(repo_root / "data" / "blueprints")


@pytest.fixture
def env(repo_root: Path) -> Iterator[Environment]:
    with open_default_environment(repo_root=repo_root) as environment:
        yield environment


def _build(env: Environment, blueprints: tuple[Blueprint, ...]) -> list[Example]:
    registry = build_default_registry()
    generator = TemplateQueryGenerator()
    examples: list[Example] = []

    for index, blueprint in enumerate(blueprints, start=1):
        compiled, issues = try_plan(blueprint, registry)
        assert compiled is not None, f"{blueprint.blueprint_id}: {[str(i) for i in issues]}"

        trace = run(compiled, env)
        assert trace.is_usable, f"{blueprint.blueprint_id}: {trace.outcome.value}"

        query = generator.generate(blueprint, variant_index=0, root_seed=env.root_seed)
        examples.append(
            assemble_example(
                blueprint=blueprint,
                plan=compiled,
                trace=trace,
                query=query,
                env=env,
                index=index,
                created_at=CREATED_AT,
            )
        )
    return examples


# ---------------------------------------------------------------------------
# Korpus bütünlüğü
# ---------------------------------------------------------------------------


def test_korpus_yuklenir(blueprints: tuple[Blueprint, ...]) -> None:
    assert len(blueprints) == 74
    assert len({bp.family_id for bp in blueprints}) == 74
    assert all(bp.utterances for bp in blueprints), "her blueprint doğal dil ifadesi taşımalı"


def test_negatif_senaryolar_temsil_edilir(blueprints: tuple[Blueprint, ...]) -> None:
    """Yalnızca mutlu yollardan oluşan bir korpus, hep tool çağıran model eğitir."""
    decisions = {bp.expected_behavior.decision for bp in blueprints}
    assert decisions == set(Decision)

    negatives = [bp for bp in blueprints if bp.is_negative]
    assert len(negatives) == 15
    by_decision = Counter(bp.expected_behavior.decision for bp in blueprints)
    assert by_decision == {
        Decision.TOOL_CALL: 57,
        Decision.CLARIFICATION: 3,
        Decision.DIRECT_ANSWER: 9,
        Decision.CANNOT_ANSWER: 5,
    }
    assert all(
        bp.expected_behavior.assistant_response_tr
        for bp in blueprints
        if bp.expected_behavior.decision is not Decision.TOOL_CALL
    )


def test_bos_sonuc_temsil_edilir(blueprints: tuple[Blueprint, ...]) -> None:
    kinds = [bp.kind.value for bp in blueprints]
    assert kinds.count("empty_result") >= 1


def test_kompozisyon_zinciri_var(blueprints: tuple[Blueprint, ...]) -> None:
    sequential = [bp for bp in blueprints if bp.kind.value == "sequential_tool_call"]
    assert sequential
    assert any(len(bp.expected_actions) >= 2 for bp in sequential)


def test_davranis_aileleri_ve_cok_turlu_oran_korunur(
    blueprints: tuple[Blueprint, ...],
) -> None:
    kinds = Counter(bp.kind.value for bp in blueprints)
    for required in {
        "parallel_tool_call",
        "expected_error",
        "error_recovery",
        "confirmation_required",
        "user_cancellation",
    }:
        assert kinds[required] > 0

    multi_turn = sum(bp.interaction_type == "multi_turn" for bp in blueprints)
    assert 0.12 <= multi_turn / len(blueprints) <= 0.15
    assert all(
        bp.conversation_prefix
        for bp in blueprints
        if bp.interaction_type == "multi_turn"
    )


def test_cikarilan_uretim_aileleri_geri_gelmez(
    blueprints: tuple[Blueprint, ...],
) -> None:
    """Veritabanı ve sipariş/fatura kapsamı yalnızca test altyapısında kalır."""
    excluded_domains = {"open_data", "accounting"}
    excluded_providers = {"izmir_ckan", "onmuhasebe_mock"}
    excluded_tools = {
        "izmir.search_datasets",
        "izmir.get_dataset_metadata",
        "izmir.query_resource",
        "izmir.filter_records",
        "accounting.create_invoice",
        "accounting.get_invoice",
        "accounting.update_invoice_note",
        "accounting.delete_draft_invoice",
    }

    assert not excluded_domains.intersection(bp.domain for bp in blueprints)
    assert not excluded_providers.intersection(bp.provider for bp in blueprints)
    assert not excluded_tools.intersection(
        action.tool_id for bp in blueprints for action in bp.expected_actions
    )
    assert not excluded_tools.intersection(
        tool_id for bp in blueprints for tool_id in bp.available_tools
    )


def test_yeni_yerel_araclar_en_az_bir_blueprintte_cagrilir(
    blueprints: tuple[Blueprint, ...],
) -> None:
    required_tools = {
        "geo.search_places",
        "geo.get_place",
        "geo.find_nearby_places",
        "geo.lookup_postal_code",
        "calendar.list_public_holidays",
        "calendar.is_public_holiday",
        "web.search",
        "web.get_result_metadata",
    }
    called_tools = {
        action.tool_id
        for blueprint in blueprints
        for action in blueprint.expected_actions
    }
    assert required_tools <= called_tools


# ---------------------------------------------------------------------------
# Doğal dil -- korpusun varlık sebebi
#
# Bu testler bir geri bildirimden doğdu: ilk sürümde ifadeler robotik yazılmıştı
# çünkü grounding validator argüman değerinin metinde BİREBİR geçmesini
# istiyordu, ben de UUID'leri, slug'ları ve koordinatları kullanıcının ağzına
# koymuştum. Yani doğal dili validator'a uydurmuştum.
#
# Çözüm `ArgOrigin.USER_MESSAGE_DERIVED` + `Blueprint.context` oldu.
# Aşağıdakiler o hatanın geri gelmesini engeller.
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_SLUG_RE = re.compile(r"\b(?!\d{4}-\d{2}-\d{2}\b)[a-z0-9]+(?:-[a-z0-9]+){2,}\b")
_COORD_RE = re.compile(r"\b\d{2}\.\d{4,}\b")
_PLACEHOLDER_RE = re.compile(r"zzz|xxx|foo|bar|lorem", re.I)


def _all_utterances(blueprints: tuple[Blueprint, ...]) -> list[tuple[str, str]]:
    return [(bp.blueprint_id, text) for bp in blueprints for text in bp.utterances]


def test_ifadelerde_uuid_yok(blueprints: tuple[Blueprint, ...]) -> None:
    """Hiçbir kullanıcı konuşurken UUID yapıştırmaz.

    Kaynak kimliği ya uygulama bağlamından (`context`) gelir ya da ajan
    zincirle bulur.
    """
    offenders = [bid for bid, text in _all_utterances(blueprints) if _UUID_RE.search(text)]
    assert not offenders, f"UUID içeren ifadeler: {sorted(set(offenders))}"


def test_ifadelerde_veri_seti_slugu_yok(blueprints: tuple[Blueprint, ...]) -> None:
    """Kullanıcı `eshot-otobus-duraklari` demez; slug'ı bilmez bile."""
    offenders = [bid for bid, text in _all_utterances(blueprints) if _SLUG_RE.search(text)]
    assert not offenders, f"slug içeren ifadeler: {sorted(set(offenders))}"


def test_ifadelerde_ham_koordinat_yok(blueprints: tuple[Blueprint, ...]) -> None:
    """Kimse "38.4192 enlem 27.1287 boylam" diye konuşmaz; konum cihazdan gelir."""
    offenders = [bid for bid, text in _all_utterances(blueprints) if _COORD_RE.search(text)]
    assert not offenders, f"koordinat içeren ifadeler: {sorted(set(offenders))}"


def test_ifadelerde_yer_tutucu_metin_yok(blueprints: tuple[Blueprint, ...]) -> None:
    """`zzzbulunmayanveriseti12345` gibi terimler doğal dil iddiasını çürütür.

    Boş sonuç senaryoları gerçekçi ama portalda bulunmayan sorgularla kurulur
    (ör. "elektrikli scooter" -- canlıda 0 sonuç döndüğü doğrulanmıştır).
    """
    offenders = [bid for bid, text in _all_utterances(blueprints) if _PLACEHOLDER_RE.search(text)]
    assert not offenders, f"yer tutucu içeren ifadeler: {sorted(set(offenders))}"


def test_baglamdan_gelen_deger_ifadede_gecmez(blueprints: tuple[Blueprint, ...]) -> None:
    """`context` tam da kullanıcının SÖYLEMEDİĞİ şey içindir.

    Değer hem bağlamda hem ifadede geçiyorsa bağlam gereksizdir ve muhtemelen
    değer yine kullanıcının ağzına konmuştur.
    """
    offenders: list[str] = []
    for blueprint in blueprints:
        for value in blueprint.context.values():
            text_value = str(value)
            if len(text_value) < 8:
                continue
            for utterance in blueprint.utterances:
                if text_value in utterance:
                    offenders.append(f"{blueprint.blueprint_id}: {text_value[:32]}")
    assert not offenders, offenders


def test_her_blueprint_birden_fazla_ifade_tasir(blueprints: tuple[Blueprint, ...]) -> None:
    """Tek ifade, paraphrase çeşitliliğine yer bırakmaz."""
    thin = [bp.blueprint_id for bp in blueprints if len(bp.utterances) < 2]
    assert not thin, f"tek ifadeli blueprint'ler: {thin}"


# ---------------------------------------------------------------------------
# Bölme -- benchmark kirlenmesinin önündeki tek engel
# ---------------------------------------------------------------------------


def test_split_sizintisi_yok(blueprints: tuple[Blueprint, ...]) -> None:
    report = split_report(blueprints)
    assert report["leaked_families"] == []
    assert report["counts"]["test"] > 0


def test_her_karar_turu_uc_splitte_de_var(
    blueprints: tuple[Blueprint, ...],
) -> None:
    by_decision: dict[Decision, set[Split]] = {}
    for blueprint in blueprints:
        assert blueprint.split is not None
        by_decision.setdefault(blueprint.expected_behavior.decision, set()).add(
            blueprint.split
        )
    assert by_decision == {decision: set(Split) for decision in Decision}


def test_splitler_blueprintte_acikca_beyan_edilir(repo_root: Path) -> None:
    paths = sorted((repo_root / "data" / "blueprints").glob("*.yaml"))
    missing = [
        path.name
        for path in paths
        if "split" not in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]
    assert not missing, f"split alanı açıkça yazılmamış blueprint'ler: {missing}"


def test_100_smoke_when2call_dagilimi(
    blueprints: tuple[Blueprint, ...],
) -> None:
    from toolcall_tr.cli.main import _canary_budget_config

    initial = allocate_canary(blueprints, target=100)
    split_counts = Counter(
        item.blueprint.split.value
        for item in initial
        if item.blueprint.split is not None
    )
    allocations = rebalance_canary(
        initial,
        blueprints=blueprints,
        budget=_canary_budget_config(target=100, split_counts=split_counts),
    )
    decisions = Counter(
        item.blueprint.expected_behavior.decision for item in allocations
    )
    call_counts = Counter(
        len(item.blueprint.expected_actions) for item in allocations
    )
    kinds = Counter(item.blueprint.kind.value for item in allocations)
    interaction_types = Counter(
        item.blueprint.interaction_type for item in allocations
    )

    assert 65 <= decisions[Decision.TOOL_CALL] <= 72
    assert 4 <= decisions[Decision.CLARIFICATION] <= 12
    assert 8 <= decisions[Decision.DIRECT_ANSWER] <= 18
    assert 7 <= decisions[Decision.CANNOT_ANSWER] <= 15
    assert 28 <= call_counts[0] <= 35
    assert 45 <= call_counts[1] <= 55
    assert 17 <= call_counts[2] <= 27
    assert 1 <= call_counts[3] <= 4
    assert 8 <= kinds["expected_error"] + kinds["error_recovery"] <= 16
    assert 12 <= interaction_types["multi_turn"] <= 15


def test_split_atamasi_deterministik() -> None:
    assert assign_split("dataset_search_by_keyword") == assign_split("dataset_search_by_keyword")


def test_yeni_family_mevcut_atamalari_degistirmez() -> None:
    """Hash tabanlı atama; sıralı sayaç olsaydı liste değişince her şey kayardı."""
    before = assign_split("dataset_search_by_keyword")
    assign_split("bambaska_yeni_bir_family")
    assert assign_split("dataset_search_by_keyword") == before


def test_ayni_family_ayni_split(blueprints: tuple[Blueprint, ...]) -> None:
    by_family: dict[str, set[Split]] = {}
    for blueprint in blueprints:
        assert blueprint.split is not None
        by_family.setdefault(blueprint.family_id, set()).add(blueprint.split)
    assert all(len(splits) == 1 for splits in by_family.values())


# ---------------------------------------------------------------------------
# Uçtan uca üretim
# ---------------------------------------------------------------------------


def test_tum_korpus_dogrulanir(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    """Kabul kriteri: her örnek tüm bloklayıcı validator'lardan geçmeli."""
    pipeline = build_default_pipeline()
    registry = build_default_registry()
    generator = TemplateQueryGenerator()

    rejected: list[str] = []
    for index, blueprint in enumerate(blueprints, start=1):
        compiled, _ = try_plan(blueprint, registry)
        assert compiled is not None
        trace = run(compiled, env)
        query = generator.generate(blueprint, variant_index=0, root_seed=env.root_seed)
        example = assemble_example(
            blueprint=blueprint,
            plan=compiled,
            trace=trace,
            query=query,
            env=env,
            index=index,
            created_at=CREATED_AT,
        )
        result = pipeline.run(
            ValidationSubject(
                blueprint=blueprint,
                plan=compiled,
                trace=trace,
                tools=example.tools,
                example=example,
            )
        )
        if not result.accepted:
            rejected.append(
                f"{blueprint.blueprint_id}: "
                + "; ".join(f"{f.validator}/{f.code}" for f in result.errors)
            )

    assert not rejected, "\n".join(rejected)


def test_uretim_deterministik(repo_root: Path, blueprints: tuple[Blueprint, ...]) -> None:
    """İki **taze** ortam, aynı korpus, birebir aynı çıktı.

    Bu test kırılıyorsa bir yerde donmamış saat, global RNG veya sıralanmamış
    bir sorgu vardır.
    """
    with open_default_environment(repo_root=repo_root) as first_env:
        first = _build(first_env, blueprints)
    with open_default_environment(repo_root=repo_root) as second_env:
        second = _build(second_env, blueprints)

    assert [e.content_hash() for e in first] == [e.content_hash() for e in second]
    assert [e.execution.trace_id for e in first] == [e.execution.trace_id for e in second]


def test_ag_olmadan_calisir(
    repo_root: Path, blueprints: tuple[Blueprint, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI ağa erişememeli -- sadece "replay'e default'lamamalı"."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("üretim sırasında ağ erişimi denendi")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    with open_default_environment(repo_root=repo_root) as environment:
        examples = _build(environment, blueprints)
    assert len(examples) == len(blueprints)


# ---------------------------------------------------------------------------
# Üretilen örneklerin özellikleri
# ---------------------------------------------------------------------------


def test_ornekler_kendi_kendine_yeterli(
    env: Environment, blueprints: tuple[Blueprint, ...]
) -> None:
    """Registry sonradan değişse bile örnek kendi tool tanımlarını taşır."""
    for example in _build(env, blueprints):
        assert example.tools
        offered = {tool.tool_id.split(".", 1)[1] for tool in example.tools}
        for call in example.ground_truth.calls:
            assert call.name in offered


def test_bagimli_cagrilar_observation_ile_araya_girer(
    env: Environment, blueprints: tuple[Blueprint, ...]
) -> None:
    sequential = [
        example
        for example in _build(env, blueprints)
        if example.scenario.kind.value == "sequential_tool_call"
    ]
    assert sequential

    for example in sequential:
        roles = [message.role.value for message in example.messages]
        call_count = len(example.ground_truth.calls)
        assert roles == [
            "user",
            *["assistant", "tool"] * call_count,
            "assistant",
        ]
        assert example.messages[-1].content == example.ground_truth.final_response_tr
        assistant_calls = [
            message.tool_calls
            for message in example.messages
            if message.role is MessageRole.ASSISTANT and message.tool_calls
        ]
        assert all(len(calls) == 1 for calls in assistant_calls)


def test_parallel_aileler_gercekten_bagimsiz_planlanir(
    blueprints: tuple[Blueprint, ...],
) -> None:
    registry = build_default_registry()
    parallel = [
        blueprint
        for blueprint in blueprints
        if blueprint.kind.value == "parallel_tool_call"
    ]
    assert parallel

    for blueprint in parallel:
        compiled, issues = try_plan(blueprint, registry)
        assert compiled is not None, [str(issue) for issue in issues]
        assert compiled.is_parallel
        assert all(not step.depends_on for step in compiled.steps)


def test_beklenen_hata_ve_kurtarma_izleri_kullanilabilir(
    env: Environment,
    blueprints: tuple[Blueprint, ...],
) -> None:
    registry = build_default_registry()
    subjects = [
        blueprint
        for blueprint in blueprints
        if blueprint.kind.value in {"expected_error", "error_recovery"}
    ]
    assert subjects

    for blueprint in subjects:
        compiled, issues = try_plan(blueprint, registry)
        assert compiled is not None, [str(issue) for issue in issues]
        trace = run(compiled, env)
        assert trace.is_usable
        assert any(step.outcome.value == "expected_error" for step in trace.steps)
        if blueprint.kind.value == "error_recovery":
            assert trace.steps[-1].outcome.value == "ok"
            assert trace.steps[-1].wrote_state


def test_yazma_cagrilarinda_acik_onay_ground_edilir(
    blueprints: tuple[Blueprint, ...],
) -> None:
    mutation_tools = {"calendar.create_event", "calendar.cancel_event"}
    mutation_blueprints = [
        blueprint
        for blueprint in blueprints
        if mutation_tools.intersection(
            action.tool_id for action in blueprint.expected_actions
        )
    ]
    assert mutation_blueprints

    for blueprint in mutation_blueprints:
        assert any("onay" in utterance.casefold() for utterance in blueprint.utterances)
        for action in blueprint.expected_actions:
            if action.tool_id in mutation_tools:
                confirmed = action.arguments["confirmed"]
                assert getattr(confirmed, "value", None) is True


def test_negatif_ornekte_cagri_yok(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    no_call_blueprints = tuple(
        blueprint
        for blueprint in blueprints
        if blueprint.expected_behavior.decision is not Decision.TOOL_CALL
    )
    assert no_call_blueprints

    for example in _build(env, no_call_blueprints):
        assert example.ground_truth.calls == ()
        assert example.scenario.expected_result == "no_call"
        assert example.ground_truth.assistant_response_tr
        assert example.messages[-1].role is MessageRole.ASSISTANT
        assert example.messages[-1].content == example.ground_truth.assistant_response_tr


def test_clarification_eksik_parametreyi_tasir(
    env: Environment, blueprints: tuple[Blueprint, ...]
) -> None:
    clarifications = [
        e for e in _build(env, blueprints) if e.scenario.decision is Decision.CLARIFICATION
    ]
    assert clarifications
    assert all(e.ground_truth.missing_parameters for e in clarifications)


def test_execution_class_durustce_raporlanir(
    env: Environment, blueprints: tuple[Blueprint, ...]
) -> None:
    """ "Tüm cevaplar canlı API'den geldi" iddiası ASLA yapılmaz."""
    classes = {c for e in _build(env, blueprints) for c in e.execution.execution_classes}
    assert ExecutionClass.LIVE_RECORDED in classes
    assert ExecutionClass.DERIVED_LOCAL in classes


def test_state_read_only_de_null(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    """Read-only sağlayıcıda state yoktur; ortam parmak izi ayrı alandadır."""
    for example in _build(env, blueprints):
        if ExecutionClass.SIMULATED in example.execution.execution_classes:
            assert example.execution.initial_state_hash is not None
            assert example.execution.final_state_hash is not None
            assert example.ground_truth.expected_final_state is not None
        else:
            assert example.execution.initial_state_hash is None
            assert example.execution.final_state_hash is None
        assert example.provenance.environment.cassette_manifest_hash is not None


def test_provenance_eksiksiz(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    """Provenance geriye dönük doldurulamaz; ilk günden eksiksiz olmalı."""
    for example in _build(env, blueprints):
        provenance = example.provenance
        assert provenance.blueprint_hash.startswith("sha256:")
        assert provenance.plan_hash.startswith("sha256:")
        assert provenance.trace_id.startswith("sha256:")
        assert provenance.environment.registry_hash.startswith("sha256:")
        assert provenance.pipeline_version
        assert provenance.canonical_json_version == 1


def test_bos_sonuc_ornegi_empty_isaretlenir(
    env: Environment, blueprints: tuple[Blueprint, ...]
) -> None:
    empties = [e for e in _build(env, blueprints) if e.scenario.kind.value == "empty_result"]
    assert empties
    assert all(e.scenario.expected_result == "empty" for e in empties)


def test_canonical_jsonl_round_trip(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    """Tüm korpus kayıpsız yazılıp geri yüklenebilmeli."""
    examples = _build(env, blueprints)
    payload = to_canonical_jsonl(examples)
    restored = [Example.model_validate(json.loads(line)) for line in payload.splitlines() if line]
    assert restored == examples


def test_ornek_kimlikleri_benzersiz(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    examples = _build(env, blueprints)
    assert len({e.id for e in examples}) == len(examples)


def test_ornek_kimligi_siradan_bagimsiz() -> None:
    first = example_id("weather", "met_weather_forecast_001", 0)
    assert first == example_id("weather", "met_weather_forecast_001", 0)
    assert first != example_id("weather", "met_weather_forecast_001", 1)
    assert first != example_id("weather", "met_weather_forecast_002", 0)


# ---------------------------------------------------------------------------
# Cassette kapsamı
# ---------------------------------------------------------------------------


def test_yetim_cassette_yok(env: Environment, blueprints: tuple[Blueprint, ...]) -> None:
    """Kullanılmayan kayıt, ölü ağırlıktır ve lisans yüzeyini gereksiz büyütür."""
    _build(env, blueprints)
    used = set(env.used_cassette_keys)
    assert used, "korpus en az bir cassette tüketmeli"
    orphans = {
        transport.store.namespace: transport.store.orphans(used)
        for transport in env.cassettes
        if transport.store.orphans(used)
    }
    assert not orphans, f"aktif sağlayıcılarda kullanılmayan cassette var: {orphans}"
