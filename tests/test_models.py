"""Canonical modeller — özellikle yazım hatalarını yükleme anında yakalayan
doğrulayıcılar.

Buradaki testlerin çoğu "geçersiz bir şey reddedildi mi?" sorusunu sorar.
Bunlar pipeline'ın en ucuz savunma hattıdır: hatalı bir blueprint hiçbir ağ
çağrısı, cassette veya LLM tokenı harcanmadan reddedilir.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.factories import literal, make_blueprint, make_environment, make_tool
from toolcall_tr.models import (
    Blueprint,
    BlueprintKind,
    CallPlan,
    ConversationTurn,
    Decision,
    ExecutedCall,
    ExecutionClass,
    ExpectedAction,
    ExpectedBehavior,
    ExpectSpec,
    ParamSpec,
    PlannedCall,
    SideEffect,
    Split,
    StepOutcome,
    StepRefArg,
    ToolSpec,
    Trace,
    parse_step_reference,
)
from toolcall_tr.models.args import LiteralArg
from toolcall_tr.models.enums import ArgOrigin

# ---------------------------------------------------------------------------
# ParamSpec -- çeviri politikası ve şema tutarlılığı
# ---------------------------------------------------------------------------


def test_turkce_parametre_adi_reddedilir() -> None:
    """Parametre anahtarı çevrilmeyen teknik bir alandır."""
    with pytest.raises(ValidationError, match="snake_case"):
        ParamSpec(name="durak_numarası", type="string", description_tr="Durak numarası.")


def test_zorunlu_parametrenin_varsayilani_olamaz() -> None:
    """Varsayılan, eksikliği maskeleyip clarification senaryolarını bozar."""
    with pytest.raises(ValidationError, match="varsayılan"):
        ParamSpec(
            name="stop_id",
            type="string",
            description_tr="Durak numarası.",
            required=True,
            has_default=True,
            default="10030",
        )


def test_array_parametresi_item_type_ister() -> None:
    with pytest.raises(ValidationError, match="item_type"):
        ParamSpec(name="fields", type="array", description_tr="Alanlar.")


def test_json_schema_ek_alana_izin_vermez() -> None:
    """Şemada olmayan argüman üretmek sıfır toleranslı bir hatadır."""
    schema = make_tool().to_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["q"]
    assert schema["properties"]["q"]["type"] == "string"


def test_none_varsayilan_ile_varsayilansiz_ayrilir() -> None:
    """``None`` geçerli bir varsayılan olabildiği için ayrı bayrak tutulur."""
    yok = ParamSpec(name="q", type="string", description_tr="Sorgu.")
    none_varsayilan = ParamSpec(
        name="q", type="string", description_tr="Sorgu.", has_default=True, default=None
    )
    assert "default" not in yok.to_json_schema()
    assert none_varsayilan.to_json_schema()["default"] is None


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------


def test_tool_id_ile_ad_uyusmali() -> None:
    with pytest.raises(ValidationError, match="uyuşmuyor"):
        make_tool(tool_id="izmir.search_datasets", name="get_dataset")


def test_yazma_islemi_canli_ortamda_calistirilamaz() -> None:
    """Spec'in açık kuralı: create/update/delete canlıda çalışmaz."""
    with pytest.raises(ValidationError, match="canlı ortamda"):
        make_tool(side_effect=SideEffect.CREATE, execution_class=ExecutionClass.LIVE_RECORDED)


def test_yazma_islemi_simule_ortamda_serbest() -> None:
    tool = make_tool(
        tool_id="onmuhasebe.create_contact",
        provider="onmuhasebe_mock",
        side_effect=SideEffect.CREATE,
        execution_class=ExecutionClass.SIMULATED,
    )
    assert tool.side_effect is SideEffect.CREATE


def test_yinelenen_parametre_reddedilir() -> None:
    param = ParamSpec(name="q", type="string", description_tr="Sorgu.")
    with pytest.raises(ValidationError, match="yinelenen parametre"):
        make_tool(parameters=(param, param))


def test_output_alani_bulunabilir() -> None:
    tool = make_tool()
    field = tool.output("result.results[*].id")
    assert field is not None
    assert field.semantic_type == "package_id"
    assert field.is_collection


def test_ayni_tanim_ayni_hash() -> None:
    assert make_tool().content_hash() == make_tool().content_hash()


# ---------------------------------------------------------------------------
# Argüman referansları
# ---------------------------------------------------------------------------


def test_kisa_gosterim_cozulur() -> None:
    assert parse_step_reference("$actions[0].result.id") == (0, "result.id")
    assert parse_step_reference("sıradan bir metin") is None


def test_sabit_deger_onceki_observation_dan_gelemez() -> None:
    """Önceki adımdan gelen değer StepRefArg ile ifade edilir."""
    with pytest.raises(ValidationError, match="StepRefArg"):
        LiteralArg(value="x", origin=ArgOrigin.PRIOR_OBSERVATION)


def test_karmasik_jsonpath_reddedilir() -> None:
    """Filtre ve joker ifadeler ground-truth'u belirsizleştirir."""
    with pytest.raises(ValidationError, match="referans yolu"):
        StepRefArg(step_index=0, path="result.results[?(@.id)].id")


# ---------------------------------------------------------------------------
# Blueprint -- yazım hatası yakalayıcıları
# ---------------------------------------------------------------------------


def test_negatif_senaryoda_tool_cagrisi_olamaz() -> None:
    with pytest.raises(ValidationError, match="beklenen tool çağrısı olmamalı"):
        make_blueprint(
            kind=BlueprintKind.SHOULD_REFUSE,
            expected_behavior=ExpectedBehavior(
                decision=Decision.CANNOT_ANSWER,
                unsupported_reason_tr="Bu portalda hava durumu verisi yok.",
                assistant_response_tr="Bu isteği mevcut araçlarla yerine getiremiyorum.",
            ),
        )


def test_tur_ve_karar_uyusmali() -> None:
    with pytest.raises(ValidationError, match="kararı gerektirir"):
        make_blueprint(
            kind=BlueprintKind.SHOULD_ASK_CLARIFICATION,
            expected_actions=(),
            expected_behavior=ExpectedBehavior(
                decision=Decision.DIRECT_ANSWER,
                assistant_response_tr="Doğrudan yanıt.",
            ),
        )


def test_clarification_eksik_parametre_ister() -> None:
    with pytest.raises(ValidationError, match="eksik parametre"):
        ExpectedBehavior(decision=Decision.CLARIFICATION)


def test_cannot_answer_gerekce_ister() -> None:
    with pytest.raises(ValidationError, match="gerekçe"):
        ExpectedBehavior(decision=Decision.CANNOT_ANSWER)


def test_no_call_karari_birebir_asistan_hedefi_ister() -> None:
    with pytest.raises(ValidationError, match="assistant_response_tr"):
        ExpectedBehavior(decision=Decision.DIRECT_ANSWER)


def test_tool_call_kararinda_asistan_cevabi_hedefi_olamaz() -> None:
    with pytest.raises(ValidationError, match="tool_call"):
        ExpectedBehavior(
            decision=Decision.TOOL_CALL,
            assistant_response_tr="Hayali final cevap.",
        )


def test_single_turn_conversation_prefix_tasiyamaz() -> None:
    with pytest.raises(ValidationError, match="single_turn"):
        make_blueprint(
            conversation_prefix=(
                ConversationTurn(role="user", content="İzmir için bakıyorum."),
                ConversationTurn(role="assistant", content="Hangi bilgiyi istersiniz?"),
            )
        )


def test_multi_turn_kullanici_asistan_prefix_cifti_ister() -> None:
    with pytest.raises(ValidationError, match="kullanıcı/asistan"):
        make_blueprint(
            interaction_type="multi_turn",
            conversation_prefix=(
                ConversationTurn(role="user", content="İzmir için bakıyorum."),
            ),
        )

    blueprint = make_blueprint(
        interaction_type="multi_turn",
        conversation_prefix=(
            ConversationTurn(role="user", content="İzmir için bakıyorum."),
            ConversationTurn(role="assistant", content="Hangi bilgiyi istersiniz?"),
        ),
    )
    assert blueprint.interaction_type == "multi_turn"


def test_sunulmayan_tool_cagrilamaz() -> None:
    """Model sunulmayan bir tool'u çağıramaz; ground truth da çağıramaz."""
    with pytest.raises(ValidationError, match="available_tools dışında"):
        make_blueprint(available_tools=("izmir.get_dataset_metadata",))


def test_ileri_referans_reddedilir() -> None:
    """Referanslar yalnızca önceki adımlara verilebilir."""
    with pytest.raises(ValidationError, match="ileri veya kendine referans"):
        make_blueprint(
            available_tools=("izmir.search_datasets", "izmir.query_resource"),
            expected_actions=(
                ExpectedAction(
                    tool_id="izmir.search_datasets",
                    arguments={"q": StepRefArg(step_index=1, path="result.id")},
                ),
                ExpectedAction(tool_id="izmir.query_resource"),
            ),
        )


def test_kendine_referans_reddedilir() -> None:
    with pytest.raises(ValidationError, match="ileri veya kendine referans"):
        make_blueprint(
            expected_actions=(
                ExpectedAction(
                    tool_id="izmir.search_datasets",
                    arguments={"q": StepRefArg(step_index=0, path="result.id")},
                ),
            ),
        )


def test_eksik_parametre_ayni_anda_bilinen_bilgi_olamaz() -> None:
    with pytest.raises(ValidationError, match="hem eksik parametre hem bilinen bilgi"):
        make_blueprint(
            kind=BlueprintKind.SHOULD_ASK_CLARIFICATION,
            expected_actions=(),
            known_information={"q": "otobüs"},
            expected_behavior=ExpectedBehavior(
                decision=Decision.CLARIFICATION,
                missing_parameters=("q",),
                assistant_response_tr="Hangi anahtar kelimeyi aramamı istersiniz?",
            ),
        )


def test_expected_error_hata_bekleyen_adim_ister() -> None:
    with pytest.raises(ValidationError, match="hata bekleyen"):
        make_blueprint(kind=BlueprintKind.EXPECTED_ERROR)


def test_expected_error_gecerli_kurulum() -> None:
    blueprint = make_blueprint(
        kind=BlueprintKind.EXPECTED_ERROR,
        expected_actions=(
            ExpectedAction(
                tool_id="izmir.search_datasets",
                arguments={"q": literal("bulunmayan_veri_seti")},
                expect=ExpectSpec(outcome="error", status_code=404),
            ),
        ),
    )
    assert blueprint.expected_actions[0].expect.status_code == 404


def test_basari_beklenen_adimda_hata_kodu_olamaz() -> None:
    with pytest.raises(ValidationError, match="belirtilemez"):
        ExpectSpec(outcome="ok", status_code=404)


def test_hash_split_ten_bagimsiz() -> None:
    """Bölme ataması blueprint'in içeriğini değiştirmez, yerini söyler."""
    train = make_blueprint(split=Split.TRAIN)
    test = make_blueprint(split=Split.TEST)
    assert train.content_hash() == test.content_hash()


def test_hash_icerik_degisince_degisir() -> None:
    a = make_blueprint()
    b = make_blueprint(user_goal="Farklı bir amaç")
    assert a.content_hash() != b.content_hash()


def test_negatif_tur_bayragi() -> None:
    assert make_blueprint(
        kind=BlueprintKind.SHOULD_REFUSE,
        expected_actions=(),
        expected_behavior=ExpectedBehavior(
            decision=Decision.CANNOT_ANSWER,
            unsupported_reason_tr="Uygun tool yok.",
            assistant_response_tr="Bu isteği karşılayabilecek bir aracım yok.",
        ),
    ).is_negative
    assert not make_blueprint().is_negative


def test_blueprint_round_trip() -> None:
    original = make_blueprint()
    restored = Blueprint.model_validate(original.model_dump(mode="json"))
    assert restored == original


# ---------------------------------------------------------------------------
# CallPlan
# ---------------------------------------------------------------------------


def _plan_step(**overrides: object) -> PlannedCall:
    defaults: dict[str, object] = {
        "step_index": 0,
        "step_id": "s0",
        "tool_id": "izmir.search_datasets",
        "arguments": {"q": literal("otobüs")},
    }
    defaults.update(overrides)
    return PlannedCall(**defaults)  # type: ignore[arg-type]


def test_depends_on_referanslarla_uyusmali() -> None:
    with pytest.raises(ValidationError, match="uyuşmuyor"):
        PlannedCall(
            step_index=1,
            step_id="s1",
            tool_id="izmir.query_resource",
            arguments={"resource_id": StepRefArg(step_index=0, path="result.id")},
            depends_on=(),
        )


def test_depends_on_otomatik_dogrulanir() -> None:
    step = PlannedCall(
        step_index=1,
        step_id="s1",
        tool_id="izmir.query_resource",
        arguments={"resource_id": StepRefArg(step_index=0, path="result.id")},
        depends_on=(0,),
    )
    assert step.depends_on == (0,)


def _plan(**overrides: object) -> CallPlan:
    defaults: dict[str, object] = {
        "blueprint_id": "izmir_search_001",
        "blueprint_hash": "sha256:" + "d" * 64,
        "registry_hash": "sha256:" + "c" * 64,
        "decision": Decision.TOOL_CALL,
        "expected_behavior": ExpectedBehavior(decision=Decision.TOOL_CALL),
        "available_tools": ("izmir.search_datasets", "izmir.query_resource"),
        "steps": (_plan_step(),),
    }
    defaults.update(overrides)
    return CallPlan(**defaults)  # type: ignore[arg-type]


def test_negatif_kararda_adim_olamaz() -> None:
    with pytest.raises(ValidationError, match="adım olmamalı"):
        _plan(
            decision=Decision.CANNOT_ANSWER,
            expected_behavior=ExpectedBehavior(
                decision=Decision.CANNOT_ANSWER,
                unsupported_reason_tr="Yok.",
                assistant_response_tr="Bu isteği yerine getiremiyorum.",
            ),
        )


def test_adim_sirasi_bozuk_reddedilir() -> None:
    with pytest.raises(ValidationError, match="adım sırası bozuk"):
        _plan(steps=(_plan_step(step_index=3),))


def test_sirali_ve_paralel_ayrimi() -> None:
    sequential = _plan(
        steps=(
            _plan_step(),
            _plan_step(
                step_index=1,
                step_id="s1",
                tool_id="izmir.query_resource",
                arguments={"resource_id": StepRefArg(step_index=0, path="result.id")},
                depends_on=(0,),
            ),
        )
    )
    assert sequential.is_sequential and not sequential.is_parallel

    parallel = _plan(
        steps=(
            _plan_step(),
            _plan_step(step_index=1, step_id="s1", tool_id="izmir.query_resource"),
        )
    )
    assert parallel.is_parallel and not parallel.is_sequential


# ---------------------------------------------------------------------------
# Trace -- determinizmin ölçüldüğü yer
# ---------------------------------------------------------------------------


def _call(**overrides: object) -> ExecutedCall:
    defaults: dict[str, object] = {
        "step_index": 0,
        "step_id": "s0",
        "tool_id": "izmir.search_datasets",
        "execution_class": ExecutionClass.LIVE_RECORDED,
        "arguments": {"q": "otobüs"},
        "outcome": StepOutcome.OK,
        "status_code": 200,
        "response": {"count": 3},
        "cassette_key": "sha256:" + "1" * 64,
    }
    defaults.update(overrides)
    return ExecutedCall(**defaults)  # type: ignore[arg-type]


def _trace(**overrides: object) -> Trace:
    defaults: dict[str, object] = {
        "blueprint_id": "izmir_search_001",
        "plan_hash": "sha256:" + "e" * 64,
        "episode_seed": 12345,
        "steps": (_call(),),
        "environment": make_environment(),
        "outcome": StepOutcome.OK,
    }
    defaults.update(overrides)
    return Trace(**defaults)  # type: ignore[arg-type]


def test_trace_id_gecikmeyi_yok_sayar() -> None:
    """Gecikme hash'e girseydi determinizm testi hep başarısız olurdu."""
    hizli = _trace(steps=(_call(latency_ms=12.0),))
    yavas = _trace(steps=(_call(latency_ms=980.5),))
    assert hizli.trace_id() == yavas.trace_id()


def test_trace_id_ham_yanit_hash_ini_yok_sayar() -> None:
    a = _trace(steps=(_call(raw_response_hash="sha256:" + "9" * 64),))
    b = _trace(steps=(_call(raw_response_hash=None),))
    assert a.trace_id() == b.trace_id()


def test_trace_id_gercek_farki_yakalar() -> None:
    a = _trace()
    b = _trace(steps=(_call(response={"count": 4}),))
    assert a.trace_id() != b.trace_id()


def test_trace_id_argumanlari_kapsar() -> None:
    a = _trace()
    b = _trace(steps=(_call(arguments={"q": "metro"}),))
    assert a.trace_id() != b.trace_id()


def test_beklenen_hata_veriye_donusur() -> None:
    """Beklenen hata ground-truth'un kendisidir; örnek korunur."""
    trace = _trace(
        steps=(_call(outcome=StepOutcome.EXPECTED_ERROR, status_code=404, response=None),),
        outcome=StepOutcome.EXPECTED_ERROR,
    )
    assert trace.is_usable


@pytest.mark.parametrize(
    "outcome",
    [
        StepOutcome.TRANSPORT_ERROR,
        StepOutcome.UNEXPECTED_ERROR,
        StepOutcome.PLAN_ERROR,
        StepOutcome.NONDETERMINISM,
    ],
)
def test_altyapi_hatasi_veriye_donusmez(outcome: StepOutcome) -> None:
    assert not _trace(outcome=outcome).is_usable


def test_derived_local_adimda_cassette_olamaz() -> None:
    """Yerel hesaplama ağ çağrısı yapmaz."""
    with pytest.raises(ValidationError, match="cassette anahtarı olamaz"):
        _call(
            execution_class=ExecutionClass.DERIVED_LOCAL,
            cassette_key="sha256:" + "1" * 64,
        )


def test_basarili_adimda_hata_mesaji_olamaz() -> None:
    with pytest.raises(ValidationError, match="hata mesajı olamaz"):
        _call(outcome=StepOutcome.OK, error="patladı")


def test_state_degisimi_tespiti() -> None:
    """Reddedilen bir yazma işlemi arkasında hiçbir şey bırakmamalıdır."""
    degismedi = _call(state_hash_before="sha256:aa", state_hash_after="sha256:aa")
    degisti = _call(state_hash_before="sha256:aa", state_hash_after="sha256:bb")
    readonly = _call()

    assert not degismedi.wrote_state
    assert degisti.wrote_state
    assert not readonly.wrote_state


def test_read_only_de_state_hash_none() -> None:
    """Read-only sağlayıcıda state yoktur; ortam parmak izi ayrı alandadır."""
    trace = _trace()
    assert trace.steps[0].state_hash_before is None
    assert trace.environment.cassette_manifest_hash is not None


def test_trace_round_trip() -> None:
    original = _trace()
    restored = Trace.model_validate(original.model_dump(mode="json"))
    assert restored.trace_id() == original.trace_id()


# ---------------------------------------------------------------------------
# Sözleşme dondurma
# ---------------------------------------------------------------------------


def test_modeller_ek_alan_kabul_etmez() -> None:
    """Yazım hatası sessizce yutulmamalı."""
    with pytest.raises(ValidationError):
        ToolSpec.model_validate({**make_tool().model_dump(mode="json"), "typo_field": 1})
