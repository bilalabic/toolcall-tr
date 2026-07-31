"""Ağ/LLM gerektirmeyen konservatif kalite validator'ları."""

from __future__ import annotations

from tests.factories import literal, make_blueprint, make_environment, make_example
from toolcall_tr.groundtruth.planner import plan
from toolcall_tr.models import (
    ExpectedAction,
    Message,
    MessageRole,
    Scenario,
    StepOutcome,
    StepRefArg,
    ToolCallRecord,
    Trace,
)
from toolcall_tr.pipeline.environment import build_izmir_registry
from toolcall_tr.validation import (
    M1_BLOCKING,
    RELEASE_BLOCKING,
    LanguageQualityValidator,
    ObservationGroundingValidator,
    TurnConsistencyValidator,
    ValidationSubject,
    build_default_pipeline,
)

REGISTRY = build_izmir_registry()
TOOLS = tuple(REGISTRY)
BLUEPRINT = make_blueprint(available_tools=tuple(REGISTRY.tool_ids()))
PLAN = plan(BLUEPRINT, REGISTRY)
TRACE = Trace(
    blueprint_id=BLUEPRINT.blueprint_id,
    plan_hash=PLAN.plan_hash(),
    episode_seed=1,
    steps=(),
    environment=make_environment(),
    outcome=StepOutcome.OK,
)


def _subject(messages: tuple[Message, ...], *, interaction_type: str = "single_turn") -> ValidationSubject:
    example = make_example(messages=messages, tools=TOOLS)
    if interaction_type != "single_turn":
        scenario = Scenario(
            decision=example.scenario.decision,
            kind=example.scenario.kind,
            interaction_type=interaction_type,  # type: ignore[arg-type]
            difficulty=example.scenario.difficulty,
            expected_result=example.scenario.expected_result,
        )
        example = example.model_copy(update={"scenario": scenario})
    return ValidationSubject(
        blueprint=BLUEPRINT,
        plan=PLAN,
        trace=TRACE,
        tools=TOOLS,
        example=example,
    )


def _tool_flow(*, final: str | None = None, observation: str = '{"count":2}') -> tuple[Message, ...]:
    messages = [
        Message(role=MessageRole.USER, content="Otobüs veri setlerini bul."),
        Message(
            role=MessageRole.ASSISTANT,
            tool_calls=(ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),),
        ),
        Message(role=MessageRole.TOOL, tool_name="search_datasets", content=observation),
    ]
    if final is not None:
        messages.append(Message(role=MessageRole.ASSISTANT, content=final))
    return tuple(messages)


def test_yeni_kalite_validatorlari_varsayilan_pipeline_da_nonblocking() -> None:
    pipeline = build_default_pipeline()
    names = {validator.name for validator in pipeline.validators}
    assert {"language", "observation", "turn"} <= names
    assert {"language", "observation", "turn"}.isdisjoint(M1_BLOCKING)


def test_release_pipeline_dil_ve_tekrari_bloklar() -> None:
    pipeline = build_default_pipeline(release=True)
    assert {"language", "duplicate"} <= pipeline.blocking
    assert pipeline.blocking == RELEASE_BLOCKING


def test_temiz_turkce_mesaj_bulgu_uretmez() -> None:
    assert list(LanguageQualityValidator().check(_subject(_tool_flow()))) == []


def test_dil_kalitesi_acik_uretim_artiklarini_yakalar() -> None:
    messages = (
        Message(
            role=MessageRole.USER,
            content="  {{şehir}} için search_datasets sonucunu getir.\x00  ",
        ),
    )
    codes = {finding.code for finding in LanguageQualityValidator().check(_subject(messages))}
    assert {
        "edge_whitespace",
        "unresolved_placeholder",
        "control_character",
        "tool_name_leakage",
    } <= codes


def test_mojibake_yakalanir_ama_tool_gozlemi_taranmaz() -> None:
    broken_user = (Message(role=MessageRole.USER, content="Ä°zmir verisini bul."),)
    assert {f.code for f in LanguageQualityValidator().check(_subject(broken_user))} == {
        "mojibake"
    }

    external_text = _tool_flow(observation='{"name":"Ä°zmir"}')
    assert list(LanguageQualityValidator().check(_subject(external_text))) == []


def test_final_sayisal_iddia_gozlemde_varsa_desteklenir() -> None:
    messages = _tool_flow(final="Toplam 2 sonuç bulundu.", observation='{"count":2}')
    assert list(ObservationGroundingValidator().check(_subject(messages))) == []


def test_final_sayisal_iddia_gozlemde_yoksa_raporlanir() -> None:
    messages = _tool_flow(final="Toplam 99 sonuç bulundu.", observation='{"count":2}')
    findings = list(ObservationGroundingValidator().check(_subject(messages)))
    assert [finding.code for finding in findings] == ["unsupported_numeric_claim"]


def test_final_cevap_yoksa_observation_kontrolu_sessizce_gecer() -> None:
    assert list(ObservationGroundingValidator().check(_subject(_tool_flow()))) == []


def test_tool_olmayan_dogrudan_cevap_observation_gerektirmez() -> None:
    messages = (
        Message(role=MessageRole.USER, content="Bir yılda kaç ay var?"),
        Message(role=MessageRole.ASSISTANT, content="Bir yılda 12 ay vardır."),
    )
    assert list(ObservationGroundingValidator().check(_subject(messages))) == []


def test_gecerli_tool_mesaj_akisi_kabul_edilir() -> None:
    assert list(TurnConsistencyValidator().check(_subject(_tool_flow()))) == []


def test_yetim_tool_mesaji_yakalanir() -> None:
    messages = (
        Message(role=MessageRole.USER, content="Otobüs verisini bul."),
        Message(role=MessageRole.TOOL, tool_name="search_datasets", content='{"count":2}'),
    )
    findings = list(TurnConsistencyValidator().check(_subject(messages)))
    assert any(finding.code == "orphan_tool_message" for finding in findings)


def test_eksik_tool_yaniti_yakalanir() -> None:
    messages = _tool_flow()[:-1]
    findings = list(TurnConsistencyValidator().check(_subject(messages)))
    assert any(finding.code == "missing_tool_responses" for finding in findings)


def test_multi_turn_etiketi_en_az_iki_kullanici_turu_gerektirir() -> None:
    findings = list(
        TurnConsistencyValidator().check(_subject(_tool_flow(), interaction_type="multi_turn"))
    )
    assert any(finding.code == "interaction_type_mismatch" for finding in findings)


def test_paralel_tool_yanitlari_farkli_sirada_gelebilir() -> None:
    messages = (
        Message(role=MessageRole.USER, content="İki aramayı da yap."),
        Message(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),
                ToolCallRecord(name="get_dataset_metadata", arguments={"dataset_id": "abc"}),
            ),
        ),
        Message(role=MessageRole.TOOL, tool_name="get_dataset_metadata", content='{"id":"abc"}'),
        Message(role=MessageRole.TOOL, tool_name="search_datasets", content='{"count":1}'),
    )
    assert list(TurnConsistencyValidator().check(_subject(messages))) == []


def test_bagimli_cagrilar_tek_mesajda_gruplanamaz() -> None:
    sequential_blueprint = make_blueprint(
        available_tools=("izmir.search_datasets", "izmir.get_dataset_metadata"),
        expected_actions=(
            ExpectedAction(
                tool_id="izmir.search_datasets",
                arguments={"q": literal("otobüs")},
            ),
            ExpectedAction(
                tool_id="izmir.get_dataset_metadata",
                arguments={
                    "dataset_id": StepRefArg(
                        step_index=0,
                        path="result.results[0].id",
                    )
                },
            ),
        ),
    )
    sequential_plan = plan(sequential_blueprint, REGISTRY)
    messages = (
        Message(role=MessageRole.USER, content="Otobüs verisinin ayrıntılarını bul."),
        Message(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),
                ToolCallRecord(
                    name="get_dataset_metadata",
                    arguments={"dataset_id": "dataset-1"},
                ),
            ),
        ),
        Message(
            role=MessageRole.TOOL,
            tool_name="search_datasets",
            content='{"result":{"results":[{"id":"dataset-1"}]}}',
        ),
        Message(
            role=MessageRole.TOOL,
            tool_name="get_dataset_metadata",
            content='{"result":{"id":"dataset-1"}}',
        ),
    )
    example = make_example(messages=messages, tools=TOOLS)
    subject = ValidationSubject(
        blueprint=sequential_blueprint,
        plan=sequential_plan,
        trace=TRACE,
        tools=TOOLS,
        example=example,
    )

    findings = list(TurnConsistencyValidator().check(subject))
    assert any(finding.code == "dependent_calls_grouped" for finding in findings)
