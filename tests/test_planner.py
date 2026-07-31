"""Faz A — Planner. Saf derleyicinin hard-fail'leri.

Buradaki her test "hatalı bir blueprint hiçbir ağ çağrısı, cassette veya LLM
tokenı harcanmadan reddedildi mi?" sorusunu sorar. Planner'ın kaçırdığı her
hata, aşağıda çok daha pahalı bir noktada ortaya çıkar.
"""

from __future__ import annotations

import pytest

from tests.factories import literal, make_blueprint
from toolcall_tr.groundtruth.planner import (
    PlanningError,
    normalize_ref_path,
    plan,
    try_plan,
)
from toolcall_tr.models import (
    ArgOrigin,
    BlueprintKind,
    Decision,
    ExpectedAction,
    ExpectedBehavior,
    ExpectSpec,
    LiteralArg,
    StepRefArg,
)
from toolcall_tr.pipeline.environment import build_izmir_registry

REGISTRY = build_izmir_registry()

SEARCH = "izmir.search_datasets"
METADATA = "izmir.get_dataset_metadata"
QUERY = "izmir.query_resource"
NEARBY = "izmir.find_nearby_stops"
BUSES = "izmir.get_approaching_buses"

ALL_TOOLS = (SEARCH, METADATA, QUERY, NEARBY, BUSES)


def _codes(blueprint_kwargs: dict[str, object]) -> set[str]:
    _, issues = try_plan(make_blueprint(**blueprint_kwargs), REGISTRY)  # type: ignore[arg-type]
    return {issue.code for issue in issues}


# ---------------------------------------------------------------------------
# Yol normalizasyonu
# ---------------------------------------------------------------------------


def test_somut_indeks_koleksiyona_cevrilir() -> None:
    """Output şemaları `[*]` ile beyan eder; referanslar somut indeks kullanır."""
    assert normalize_ref_path("result.results[0].id") == "result.results[*].id"
    assert normalize_ref_path("result.resources[3].id") == "result.resources[*].id"
    assert normalize_ref_path("result.count") == "result.count"


# ---------------------------------------------------------------------------
# Başarılı planlama
# ---------------------------------------------------------------------------


def test_tek_adimli_plan() -> None:
    blueprint = make_blueprint(
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs durak")}),
        ),
    )
    result = plan(blueprint, REGISTRY)
    assert len(result.steps) == 1
    assert result.steps[0].step_id == "izmir_search_001_s0"
    assert result.steps[0].depends_on == ()
    assert not result.is_sequential


def test_uc_adimli_zincir_planlanir() -> None:
    """arama -> package_id -> metadata -> resource_id -> tablo."""
    result = plan(_chain_blueprint(), REGISTRY)
    assert len(result.steps) == 3
    assert result.steps[1].depends_on == (0,)
    assert result.steps[2].depends_on == (1,)
    assert result.is_sequential
    assert not result.is_parallel


def test_paralel_plan_tespit_edilir() -> None:
    blueprint = make_blueprint(
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("taksi durağı")}),
        ),
    )
    result = plan(blueprint, REGISTRY)
    assert result.is_parallel
    assert not result.is_sequential


def test_negatif_senaryo_bos_plan_uretir() -> None:
    blueprint = make_blueprint(
        kind=BlueprintKind.SHOULD_REFUSE,
        available_tools=ALL_TOOLS,
        expected_actions=(),
        expected_behavior=ExpectedBehavior(
            decision=Decision.CANNOT_ANSWER,
            unsupported_reason_tr="Bu portalda hava durumu tahmini yok.",
            assistant_response_tr="Bu araçlarla hava durumu tahmini sağlayamıyorum.",
        ),
    )
    result = plan(blueprint, REGISTRY)
    assert result.steps == ()
    assert result.decision is Decision.CANNOT_ANSWER


def test_plan_hash_kararli() -> None:
    assert plan(_chain_blueprint(), REGISTRY).plan_hash() == (
        plan(_chain_blueprint(), REGISTRY).plan_hash()
    )


def test_plan_registry_hash_ini_tasir() -> None:
    """Registry değişirse plan geçersizleşir; hash bunu görünür kılar."""
    assert plan(_chain_blueprint(), REGISTRY).registry_hash == REGISTRY.content_hash()


# ---------------------------------------------------------------------------
# Hard-fail'ler
# ---------------------------------------------------------------------------


def test_registryde_olmayan_tool_yakalanir() -> None:
    codes = _codes(
        {
            "available_tools": ("izmir.hava_durumu",),
            "expected_actions": (ExpectedAction(tool_id="izmir.hava_durumu"),),
        }
    )
    assert "unknown_tool" in codes


def test_semada_olmayan_parametre_yakalanir() -> None:
    codes = _codes(
        {
            "available_tools": ALL_TOOLS,
            "expected_actions": (
                ExpectedAction(
                    tool_id=SEARCH,
                    arguments={"q": literal("otobüs"), "sirala": literal("artan")},
                ),
            ),
        }
    )
    assert "unknown_parameter" in codes


def test_zorunlu_parametre_eksikligi_yakalanir() -> None:
    codes = _codes(
        {
            "available_tools": ALL_TOOLS,
            "expected_actions": (ExpectedAction(tool_id=QUERY, arguments={"limit": literal(5)}),),
        }
    )
    assert "missing_required_parameter" in codes


def test_tip_uyusmazligi_yakalanir() -> None:
    codes = _codes(
        {
            "available_tools": ALL_TOOLS,
            "expected_actions": (
                ExpectedAction(tool_id=BUSES, arguments={"stop_id": literal("on bin otuz")}),
            ),
        }
    )
    assert "type_mismatch" in codes


def test_output_semasinda_olmayan_alana_referans_yakalanir() -> None:
    """En değerli kontrol: hiçbir ağ çağrısı yapılmadan reddedilir."""
    codes = _codes(
        {
            "available_tools": ALL_TOOLS,
            "expected_actions": (
                ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
                ExpectedAction(
                    tool_id=METADATA,
                    arguments={
                        "dataset_id": StepRefArg(
                            step_index=0, path="result.results[0].uydurma_alan"
                        )
                    },
                ),
            ),
        }
    )
    assert "invalid_reference" in codes


def test_semantik_tip_uyusmazligi_yakalanir() -> None:
    """Bir `package_id`, `resource_id` yerine geçemez.

    Elle yazılmış function graph yerine `semantic_type` kullanmanın bedava
    kazançlarından biri: bu kontrol hiçbir ek yapılandırma olmadan çalışır.
    """
    codes = _codes(
        {
            "available_tools": ALL_TOOLS,
            "expected_actions": (
                ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
                ExpectedAction(
                    tool_id=QUERY,
                    # `result.results[*].id` package_id üretir, resource_id değil.
                    arguments={
                        "resource_id": StepRefArg(step_index=0, path="result.results[0].id")
                    },
                ),
            ),
        }
    )
    assert "semantic_type_mismatch" in codes


def test_uyumlu_semantik_tip_kabul_edilir() -> None:
    """`package_id` -> `dataset_id` uyumludur."""
    _, issues = try_plan(
        make_blueprint(
            available_tools=ALL_TOOLS,
            expected_actions=(
                ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
                ExpectedAction(
                    tool_id=METADATA,
                    arguments={
                        "dataset_id": StepRefArg(step_index=0, path="result.results[0].name")
                    },
                ),
            ),
        ),
        REGISTRY,
    )
    assert issues == []


def test_tum_hatalar_tek_gecişte_toplanir() -> None:
    """İlk hatada durmak, blueprint'in kaç sebeple hatalı olduğunu gizlerdi."""
    _, issues = try_plan(
        make_blueprint(
            available_tools=ALL_TOOLS,
            expected_actions=(
                ExpectedAction(
                    tool_id=SEARCH,
                    arguments={"q": literal(42), "yok_boyle": literal("x")},
                ),
            ),
        ),
        REGISTRY,
    )
    codes = [issue.code for issue in issues]
    assert "type_mismatch" in codes
    assert "unknown_parameter" in codes
    assert len(issues) >= 2


def test_planning_error_tum_sorunlari_mesajda_tasir() -> None:
    blueprint = make_blueprint(
        available_tools=ALL_TOOLS,
        expected_actions=(ExpectedAction(tool_id=QUERY, arguments={}),),
    )
    with pytest.raises(PlanningError) as excinfo:
        plan(blueprint, REGISTRY)
    assert "missing_required_parameter" in str(excinfo.value)
    assert excinfo.value.blueprint_id == "izmir_search_001"


def test_sunulan_ama_var_olmayan_tool_yakalanir() -> None:
    """Distractor listesindeki bir yazım hatası da hatadır."""
    codes = _codes(
        {
            "available_tools": (SEARCH, "izmir.query_resourse"),
            "expected_actions": (
                ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs")}),
            ),
        }
    )
    assert "unknown_tool" in codes


# ---------------------------------------------------------------------------
# Beklenen hata planı
# ---------------------------------------------------------------------------


def test_beklenen_hata_plana_tasinir() -> None:
    blueprint = make_blueprint(
        kind=BlueprintKind.EXPECTED_ERROR,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(
                tool_id=METADATA,
                arguments={
                    "dataset_id": LiteralArg(
                        value="izmir-metro-sefer-saatleri", origin=ArgOrigin.USER_MESSAGE
                    )
                },
                expect=ExpectSpec(outcome="error", status_code=404),
            ),
        ),
    )
    result = plan(blueprint, REGISTRY)
    assert result.steps[0].expect.outcome == "error"
    assert result.steps[0].expect.status_code == 404


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _chain_blueprint() -> object:
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
