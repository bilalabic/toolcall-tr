"""Faz B — Runner. Determinizm ve hata sınıflandırması.

En kritik test `test_ayni_plan_ayni_trace_id`: aynı plan + aynı seed + aynı
cassette seti daima aynı `trace_id` üretmeli. Üretmiyorsa bir yerde donmamış
bir saat, global bir RNG veya sıralanmamış bir sorgu vardır.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.factories import literal, make_blueprint
from toolcall_tr.groundtruth.planner import plan
from toolcall_tr.groundtruth.runner import (
    Environment,
    ReferenceResolutionError,
    episode_seed,
    resolve_path,
    run,
)
from toolcall_tr.models import (
    ArgOrigin,
    Blueprint,
    BlueprintKind,
    Decision,
    ExecutionClass,
    ExpectedAction,
    ExpectedBehavior,
    ExpectSpec,
    StepOutcome,
    StepRefArg,
)
from toolcall_tr.pipeline.environment import build_izmir_registry, open_izmir_environment

REGISTRY = build_izmir_registry()

SEARCH = "izmir.search_datasets"
METADATA = "izmir.get_dataset_metadata"
QUERY = "izmir.query_resource"
NEARBY = "izmir.find_nearby_stops"
BUSES = "izmir.get_approaching_buses"
ALL_TOOLS = (SEARCH, METADATA, QUERY, NEARBY, BUSES)

STOPS_ROW_COUNT = 11783
STOP_EMPTY = 15532


@pytest.fixture
def env(repo_root: Path) -> Iterator[Environment]:
    with open_izmir_environment(repo_root=repo_root) as environment:
        yield environment


def _execute(env: Environment, blueprint: Blueprint, **kwargs: Any) -> Any:
    return run(plan(blueprint, REGISTRY), env, **kwargs)


# ---------------------------------------------------------------------------
# Seed ve yol çözümü
# ---------------------------------------------------------------------------


def test_seed_siradan_bagimsiz() -> None:
    """Blueprint #21 eklemek #1-20'nin verisini değiştirmemeli."""
    first = episode_seed(42891, "izmir_search_001", 0)
    assert episode_seed(42891, "izmir_search_001", 0) == first
    assert episode_seed(42891, "izmir_search_002", 0) != first
    assert episode_seed(42891, "izmir_search_001", 1) != first


def test_yol_cozumu() -> None:
    payload = {"result": {"results": [{"id": "a"}, {"id": "b"}], "count": 2}}
    assert resolve_path(payload, "result.count") == 2
    assert resolve_path(payload, "result.results[1].id") == "b"


def test_bos_listede_referans_gurultulu_patlar() -> None:
    with pytest.raises(ReferenceResolutionError, match="boş veya beklenenden kısa"):
        resolve_path({"result": {"results": []}}, "result.results[0].id")


def test_olmayan_anahtar_gurultulu_patlar() -> None:
    with pytest.raises(ReferenceResolutionError, match="anahtarı yanıtta yok"):
        resolve_path({"result": {}}, "result.yok.id")


# ---------------------------------------------------------------------------
# Uçtan uca çalıştırma
# ---------------------------------------------------------------------------


def test_uc_adimli_zincir_calisir(env: Environment) -> None:
    """Zincirin her halkası gerçek veriyle bağlanır; hiçbir kimlik elle yazılmaz."""
    trace = _execute(env, _chain_blueprint())

    assert trace.outcome is StepOutcome.OK
    assert trace.is_usable
    assert len(trace.steps) == 3

    # Adım 1'in argümanı adım 0'ın çıktısından geldi.
    assert trace.steps[1].arguments["dataset_id"] == "eshot-otobus-duraklari"
    # Adım 2'nin argümanı adım 1'in çıktısından geldi.
    assert trace.steps[2].arguments["resource_id"] == "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
    assert trace.steps[2].response["result"]["total"] == STOPS_ROW_COUNT


def test_ayni_plan_ayni_trace_id(repo_root: Path) -> None:
    """Yeniden üretilebilirliğin tek satırlık kanıtı.

    İki **taze** ortam; aynı plan; aynı seed. `trace_id` birebir eşit olmalı.
    """
    blueprint = _chain_blueprint()
    compiled = plan(blueprint, REGISTRY)

    with open_izmir_environment(repo_root=repo_root) as first_env:
        first = run(compiled, first_env)
    with open_izmir_environment(repo_root=repo_root) as second_env:
        second = run(compiled, second_env)

    assert first.trace_id() == second.trace_id()


def test_farkli_variant_farkli_seed_ama_ayni_sonuc(env: Environment) -> None:
    """Varyant indeksi seed'i değiştirir; read-only sonucu değiştirmez."""
    compiled = plan(_chain_blueprint(), REGISTRY)
    a = run(compiled, env, variant_index=0)
    b = run(compiled, env, variant_index=1)

    assert a.episode_seed != b.episode_seed
    assert a.trace_id() != b.trace_id()  # variant_index hash'e girer
    assert [s.response for s in a.steps] == [s.response for s in b.steps]


def test_ag_olmadan_calisir(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tüm boru hattı, soket açılamazken bile tamamlanmalı."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("çalıştırma sırasında ağ erişimi denendi")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    with open_izmir_environment(repo_root=repo_root) as environment:
        trace = _execute(environment, _chain_blueprint())
    assert trace.outcome is StepOutcome.OK


# ---------------------------------------------------------------------------
# Hata sınıflandırması -- dört sınıf ayrı ele alınmalı
# ---------------------------------------------------------------------------


def test_beklenen_hata_veriye_donusur(env: Environment) -> None:
    """404, plan onu bekliyorsa ground-truth'un kendisidir."""
    blueprint = make_blueprint(
        blueprint_id="izmir_missing_dataset_001",
        family_id="izmir_missing_dataset",
        kind=BlueprintKind.EXPECTED_ERROR,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": literal("izmir-metro-sefer-saatleri")},
                expect=ExpectSpec(outcome="error", status_code=404),
            ),
        ),
    )
    trace = _execute(env, blueprint)

    assert trace.steps[0].outcome is StepOutcome.EXPECTED_ERROR
    assert trace.steps[0].status_code == 404
    assert trace.outcome is StepOutcome.EXPECTED_ERROR
    assert trace.is_usable, "beklenen hata örneği korunmalı"


def test_yanlis_durum_kodu_beklentiyi_bozar(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_wrong_code_001",
        family_id="izmir_wrong_code",
        kind=BlueprintKind.EXPECTED_ERROR,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": literal("izmir-metro-sefer-saatleri")},
                expect=ExpectSpec(outcome="error", status_code=409),
            ),
        ),
    )
    trace = _execute(env, blueprint)
    assert trace.steps[0].outcome is StepOutcome.UNEXPECTED_ERROR
    assert not trace.is_usable


def test_hata_beklenirken_basari_de_uyusmazliktir(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_should_fail_001",
        family_id="izmir_should_fail",
        kind=BlueprintKind.EXPECTED_ERROR,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={"q": literal("otobüs")},
                expect=ExpectSpec(outcome="error", status_code=404),
            ),
        ),
    )
    trace = _execute(env, blueprint)
    assert trace.steps[0].outcome is StepOutcome.UNEXPECTED_ERROR
    assert "başarılı oldu" in (trace.steps[0].error or "")
    assert not trace.is_usable


def test_bos_sonuca_referans_plan_hatasidir(env: Environment) -> None:
    """Plan statik geçerliydi ama gerçek veride o eleman yok.

    Bu bir blueprint hatasıdır: yazar sabit fixture kimliği kullanmalı ya da
    senaryoyu düzeltmeli. Sessizce geçilmez.
    """
    blueprint = make_blueprint(
        blueprint_id="izmir_empty_ref_001",
        family_id="izmir_empty_ref",
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("elektrikli scooter")}),
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": StepRefArg(step_index=0, path="result.results[0].name")},
            ),
        ),
    )
    trace = _execute(env, blueprint)

    assert trace.steps[0].outcome is StepOutcome.OK
    assert trace.steps[1].outcome is StepOutcome.PLAN_ERROR
    assert not trace.is_usable


def test_iptal_sonrasi_adimlar_atlanir(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_abort_001",
        family_id="izmir_abort",
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("elektrikli scooter")}),
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": StepRefArg(step_index=0, path="result.results[0].name")},
            ),
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
        ),
    )
    trace = _execute(env, blueprint)
    assert trace.steps[2].outcome is StepOutcome.SKIPPED
    assert "atlandı" in (trace.steps[2].error or "")


# ---------------------------------------------------------------------------
# Boş sonuç ve yerel hesaplama
# ---------------------------------------------------------------------------


def test_bos_sonuc_basarilidir(env: Environment) -> None:
    """ "Yaklaşan otobüs yok" doğru bir cevaptır, hata değil."""
    blueprint = make_blueprint(
        blueprint_id="izmir_no_buses_001",
        family_id="izmir_no_buses",
        kind=BlueprintKind.EMPTY_RESULT,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=BUSES, arguments={"stop_id": literal(STOP_EMPTY)}),
        ),
    )
    trace = _execute(env, blueprint)

    assert trace.outcome is StepOutcome.OK
    assert trace.is_usable
    assert trace.steps[0].response == {"count": 0, "results": []}


def test_yerel_hesaplama_cassette_kullanmaz(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_nearby_001",
        family_id="izmir_nearby",
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=NEARBY,
                arguments={
                    "latitude": literal(38.4192),
                    "longitude": literal(27.1287),
                    "radius_m": literal(400, ArgOrigin.SCHEMA_DEFAULT),
                },
            ),
        ),
    )
    trace = _execute(env, blueprint)

    step = trace.steps[0]
    assert step.outcome is StepOutcome.OK
    assert step.execution_class is ExecutionClass.DERIVED_LOCAL
    assert step.cassette_key is None
    assert step.response["count"] > 0


def test_yerel_ve_canli_tool_ayni_planda(env: Environment) -> None:
    """`durak_id` semantik tipi yerel sonucu canlı tool'a bağlar."""
    blueprint = make_blueprint(
        blueprint_id="izmir_nearby_buses_001",
        family_id="izmir_nearby_buses",
        kind=BlueprintKind.SEQUENTIAL_TOOL_CALL,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=NEARBY,
                arguments={"latitude": literal(38.4192), "longitude": literal(27.1287)},
            ),
            ExpectedAction(
                tool_id=BUSES,
                arguments={"stop_id": StepRefArg(step_index=0, path="results[0].stop_id")},
            ),
        ),
    )
    compiled = plan(blueprint, REGISTRY)
    assert compiled.is_sequential

    trace = run(compiled, env)
    # İlk adım daima çalışır; ikincisinin cassette'i varsa sonuç OK olur,
    # yoksa taşıma hatası -- her iki durumda da referans çözülmüş olmalı.
    assert trace.steps[0].outcome is StepOutcome.OK
    assert isinstance(trace.steps[1].arguments.get("stop_id"), int)


# ---------------------------------------------------------------------------
# Ortam parmak izi
# ---------------------------------------------------------------------------


def test_state_hash_read_only_de_none(env: Environment) -> None:
    """Read-only sağlayıcıda state yoktur; cassette hash'i ayrı alandadır."""
    trace = _execute(env, _chain_blueprint())

    assert trace.state_delta is None
    assert all(step.state_hash_before is None for step in trace.steps)
    assert trace.environment.cassette_manifest_hash is not None
    assert trace.environment.snapshot_hashes["eshot_stops"].startswith("sha256:")


def test_saat_donmus(env: Environment) -> None:
    assert env.now == datetime(2026, 7, 28, 6, 0, tzinfo=UTC)
    assert env.fingerprint.frozen_now == env.now


def test_kullanilan_cassetteler_izlenir(env: Environment) -> None:
    """Yetim kayıt tespiti buna dayanır."""
    _execute(env, _chain_blueprint())
    assert len(env.used_cassette_keys) == 3
    assert all(key.startswith("sha256:") for key in env.used_cassette_keys)


def test_negatif_senaryo_hicbir_sey_calistirmaz(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_refuse_001",
        family_id="izmir_refuse",
        kind=BlueprintKind.SHOULD_REFUSE,
        available_tools=ALL_TOOLS,
        expected_actions=(),
        expected_behavior=ExpectedBehavior(
            decision=Decision.CANNOT_ANSWER,
            unsupported_reason_tr="Bu portalda hava durumu tahmini bulunmuyor.",
            assistant_response_tr="Bu araçlarla hava durumu tahmini sağlayamıyorum.",
        ),
    )
    trace = _execute(env, blueprint)

    assert trace.steps == ()
    assert trace.outcome is StepOutcome.OK
    assert trace.is_usable
    assert env.used_cassette_keys == set()


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _chain_blueprint() -> Blueprint:
    return make_blueprint(
        blueprint_id="izmir_chain_001",
        family_id="izmir_dataset_chain",
        kind=BlueprintKind.SEQUENTIAL_TOOL_CALL,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs durak")}),
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": StepRefArg(step_index=0, path="result.results[0].name")},
            ),
            ExpectedAction(
                tool_id=QUERY,
                arguments={
                    "resource_id": StepRefArg(step_index=1, path="result.resources[0].id"),
                    "limit": literal(5, ArgOrigin.SCHEMA_DEFAULT),
                },
            ),
        ),
    )
