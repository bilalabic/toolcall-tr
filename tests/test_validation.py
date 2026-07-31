"""Validator zinciri — gerçek trace'ler üzerinde.

Validator'lar kaydedilmiş bir `Trace` okur ve hiçbir şeyi yeniden
çalıştırmaz; bu testler de öyle davranır.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.factories import literal, make_blueprint, make_environment, make_example
from toolcall_tr.groundtruth.planner import plan
from toolcall_tr.groundtruth.runner import Environment, run
from toolcall_tr.models import (
    ArgOrigin,
    BlueprintKind,
    Decision,
    ExpectedAction,
    ExpectedBehavior,
    ExpectSpec,
    LiteralArg,
    Severity,
    StepOutcome,
    StepRefArg,
    Trace,
)
from toolcall_tr.pipeline.environment import build_izmir_registry, open_izmir_environment
from toolcall_tr.validation import (
    M1_BLOCKING,
    DuplicateValidator,
    ExecutionValidator,
    GroundingValidator,
    PIIValidator,
    RegistryValidator,
    SchemaValidator,
    ValidationPipeline,
    ValidationSubject,
    build_default_pipeline,
    looks_empty,
)

REGISTRY = build_izmir_registry()
TOOLS = tuple(REGISTRY)

SEARCH = "izmir.search_datasets"
METADATA = "izmir.get_dataset_metadata"
QUERY = "izmir.query_resource"
BUSES = "izmir.get_approaching_buses"
ALL_TOOLS = tuple(REGISTRY.tool_ids())

STOP_EMPTY = 15532

#: Duplicate validator yalnızca `Example` okur; trace'in içeriği önemsizdir.
_EMPTY_TRACE = Trace(
    blueprint_id="izmir_search_001",
    plan_hash="sha256:" + "e" * 64,
    episode_seed=1,
    steps=(),
    environment=make_environment(),
    outcome=StepOutcome.OK,
)


@pytest.fixture
def env(repo_root: Path) -> Iterator[Environment]:
    with open_izmir_environment(repo_root=repo_root) as environment:
        yield environment


def _subject(env: Environment, blueprint: Any, **kwargs: Any) -> ValidationSubject:
    compiled = plan(blueprint, REGISTRY)
    trace = run(compiled, env)
    return ValidationSubject(blueprint=blueprint, plan=compiled, trace=trace, tools=TOOLS, **kwargs)


def _example_subject(example: Any) -> ValidationSubject:
    """Yalnızca `Example` gerektiren validator'lar (duplicate) için hafif özne."""
    blueprint = _search_blueprint()
    compiled = plan(blueprint, REGISTRY)
    return ValidationSubject(
        blueprint=blueprint,
        plan=compiled,
        trace=_EMPTY_TRACE,
        tools=TOOLS,
        example=example,
    )


def _search_blueprint(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "available_tools": ALL_TOOLS,
        "expected_actions": (
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs durak")}),
        ),
    }
    defaults.update(overrides)
    return make_blueprint(**defaults)


# ---------------------------------------------------------------------------
# looks_empty -- sağlayıcıların boş sonuç biçimleri farklı
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        [],
        None,
        {"count": 0, "results": []},
        {"result": {"count": 0, "results": []}},
        {"result": {"total": 0, "records": []}},
    ],
)
def test_bos_sonuc_bicimleri_taninir(response: Any) -> None:
    assert looks_empty(response)


@pytest.mark.parametrize(
    "response",
    [
        [{"a": 1}],
        {"count": 3, "results": [{"a": 1}]},
        {"result": {"total": 11783, "records": [{"a": 1}]}},
    ],
)
def test_dolu_sonuc_bos_sayilmaz(response: Any) -> None:
    assert not looks_empty(response)


# ---------------------------------------------------------------------------
# Boru hattı
# ---------------------------------------------------------------------------


def test_gecerli_ornek_kabul_edilir(env: Environment) -> None:
    result = build_default_pipeline().run(_subject(env, _search_blueprint()))
    assert result.accepted, [f.message_tr for f in result.errors]
    assert "pii" in result.validators_run


def test_pii_daima_bloklayici() -> None:
    """PIIScanner asla devre dışı bırakılmaz ve asla uyarıya indirilmez."""
    assert "pii" in M1_BLOCKING


def test_bloklayici_olmayan_validator_uyariya_indirilir(env: Environment) -> None:
    """Olgunlaşmamış bir kontrol korpusu sessizce budayamamalı."""
    subject = _subject(env, _search_blueprint())
    pipeline = ValidationPipeline([RegistryValidator()], blocking=frozenset())

    # Sunulmayan bir tool ekleyerek hata ürettir.
    broken = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=(),
    )
    result = pipeline.run(broken)
    assert result.findings
    assert all(f.severity is Severity.WARNING for f in result.findings)
    assert result.accepted


def test_tanimsiz_bloklayici_validator_reddedilir() -> None:
    with pytest.raises(ValueError, match="tanımsız validator"):
        ValidationPipeline([RegistryValidator()], blocking=frozenset({"yok_boyle"}))


def test_hata_kodu_dagilimi_uretilir(env: Environment) -> None:
    subject = _subject(env, _search_blueprint())
    broken = ValidationSubject(
        blueprint=subject.blueprint, plan=subject.plan, trace=subject.trace, tools=()
    )
    result = ValidationPipeline([RegistryValidator()], blocking=frozenset({"registry"})).run(broken)
    assert result.code_counts()["unknown_tool"] >= 1
    assert not result.accepted


# ---------------------------------------------------------------------------
# Registry ve şema
# ---------------------------------------------------------------------------


def test_sunulmayan_tool_yakalanir(env: Environment) -> None:
    subject = _subject(env, _search_blueprint())
    broken = ValidationSubject(
        blueprint=subject.blueprint, plan=subject.plan, trace=subject.trace, tools=()
    )
    findings = list(RegistryValidator().check(broken))
    assert any(f.code == "unknown_tool" for f in findings)


def test_gecerli_argumanlar_sema_hatasi_uretmez(env: Environment) -> None:
    subject = _subject(env, _search_blueprint())
    assert list(SchemaValidator().check(subject)) == []


# ---------------------------------------------------------------------------
# Grounding -- kaynak beyan edilir, sonra gerçekten aranır
# ---------------------------------------------------------------------------


def test_fabricated_arguman_reddedilir(env: Environment) -> None:
    blueprint = _search_blueprint(
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={"q": LiteralArg(value="otobüs durak", origin=ArgOrigin.FABRICATED)},
            ),
        )
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert any(f.code == "fabricated_argument" for f in findings)


def test_yanlis_varsayilan_beyani_yakalanir(env: Environment) -> None:
    """`q` zorunludur ve varsayılanı yoktur; öyle beyan etmek hatadır."""
    blueprint = _search_blueprint(
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={"q": LiteralArg(value="otobüs", origin=ArgOrigin.SCHEMA_DEFAULT)},
            ),
        )
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert any(f.code == "false_default_claim" for f in findings)


def test_gercek_varsayilan_beyani_kabul_edilir(env: Environment) -> None:
    blueprint = _search_blueprint(
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": literal("otobüs durak"),
                    "rows": LiteralArg(value=5, origin=ArgOrigin.SCHEMA_DEFAULT),
                },
            ),
        )
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert not [f for f in findings if f.code == "false_default_claim"]


def test_turetilmis_deger_ek_soyarak_dogrulanir(env: Environment) -> None:
    """Doğal Türkçe'nin mümkün olmasını sağlayan kural.

    Kullanıcı "Otobüs duraklarıyla ilgili..." der; argüman "otobüs durak"tır.
    Birebir arama başarısız olurdu.
    """
    blueprint = _search_blueprint(
        utterances=("Otobüs duraklarıyla ilgili ne tür veriler var?",),
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": LiteralArg(value="otobüs durak", origin=ArgOrigin.USER_MESSAGE_DERIVED)
                },
            ),
        ),
    )
    subject = _subject(env, blueprint)
    example = make_example(user_text="Otobüs duraklarıyla ilgili ne tür veriler var?")
    grounded = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=TOOLS,
        example=example,
    )
    assert list(GroundingValidator().check(grounded)) == []


def test_turetilmis_deger_ilgisizse_reddedilir(env: Environment) -> None:
    """Gevşetme, uydurma argümanı görünmez yapmamalı."""
    blueprint = _search_blueprint(
        utterances=("Yarın hava nasıl olacak?",),
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": LiteralArg(value="taksi durak", origin=ArgOrigin.USER_MESSAGE_DERIVED)
                },
            ),
        ),
    )
    subject = _subject(env, blueprint)
    ungrounded = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=TOOLS,
        example=make_example(user_text="Yarın hava nasıl olacak?"),
    )
    findings = list(GroundingValidator().check(ungrounded))
    assert any(f.code == "ungrounded_argument" for f in findings)


def test_sayi_alt_dizesi_grounding_sayilmaz(env: Environment) -> None:
    blueprint = _search_blueprint(
        utterances=("En fazla 300 kayıt getir.",),
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": literal("otobüs durak"),
                    "rows": LiteralArg(value=3, origin=ArgOrigin.USER_MESSAGE),
                },
            ),
        ),
    )
    subject = _subject(env, blueprint)
    example = make_example(user_text="Otobüs duraklarından en fazla 300 kayıt getir.")
    ungrounded = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=TOOLS,
        example=example,
    )

    findings = list(GroundingValidator().check(ungrounded))

    assert any(
        finding.code == "ungrounded_argument" and finding.field == "rows"
        for finding in findings
    )


def test_ek_almis_yil_birebir_grounding_sayilir(env: Environment) -> None:
    blueprint = _search_blueprint(
        utterances=("2010'dan başlayan kayıtları getir.",),
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": literal("otobüs durak"),
                    "rows": LiteralArg(value=2010, origin=ArgOrigin.USER_MESSAGE),
                },
            ),
        ),
    )
    subject = _subject(env, blueprint)
    grounded = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=TOOLS,
        example=make_example(
            user_text="Otobüs durak kayıtlarını 2010'dan başlayarak getir."
        ),
    )

    findings = list(GroundingValidator().check(grounded))

    assert not [
        finding
        for finding in findings
        if finding.code == "ungrounded_argument" and finding.field == "rows"
    ]


def test_metin_alt_dizesi_grounding_sayilmaz(env: Environment) -> None:
    blueprint = _search_blueprint(
        utterances=("TRAMVAY verisini bul.",),
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={
                    "q": LiteralArg(value="TR", origin=ArgOrigin.USER_MESSAGE),
                },
            ),
        ),
    )
    subject = _subject(env, blueprint)
    ungrounded = ValidationSubject(
        blueprint=subject.blueprint,
        plan=subject.plan,
        trace=subject.trace,
        tools=TOOLS,
        example=make_example(user_text="TRAMVAY verisini bul."),
    )

    findings = list(GroundingValidator().check(ungrounded))

    assert any(finding.code == "ungrounded_argument" for finding in findings)


def test_sistem_baglami_beyan_edilmeliyse_reddedilir(env: Environment) -> None:
    """`SYSTEM_STATE` beyanı `context` ile desteklenmeli.

    Aksi hâlde "bu değer sistemden geldi" demek, uydurmanın kibar hâli olurdu.
    """
    blueprint = _search_blueprint(
        context={},
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={"q": LiteralArg(value="otobüs", origin=ArgOrigin.SYSTEM_STATE)},
            ),
        ),
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert any(f.code == "undeclared_context" for f in findings)


def test_beyan_edilmis_sistem_baglami_kabul_edilir(env: Environment) -> None:
    blueprint = _search_blueprint(
        context={"acik_arama": "otobüs"},
        expected_actions=(
            ExpectedAction(
                tool_id=SEARCH,
                arguments={"q": LiteralArg(value="otobüs", origin=ArgOrigin.SYSTEM_STATE)},
            ),
        ),
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert not [f for f in findings if f.code == "undeclared_context"]


def test_referans_argumani_grounding_gerektirmez(env: Environment) -> None:
    """Referansın geçerliliğini planner zaten kanıtladı."""
    blueprint = _search_blueprint(
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("otobüs durak")}),
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": StepRefArg(step_index=0, path="result.results[0].name")},
            ),
        )
    )
    findings = list(GroundingValidator().check(_subject(env, blueprint)))
    assert findings == []


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_beklenen_hata_execution_hatasi_uretmez(env: Environment) -> None:
    """404, plan onu bekliyorsa doğru sonuçtur."""
    blueprint = make_blueprint(
        blueprint_id="izmir_missing_001",
        family_id="izmir_missing",
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
    findings = list(ExecutionValidator().check(_subject(env, blueprint)))
    assert findings == []


def test_bos_sonuc_izinli_toolda_hata_degil(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_empty_001",
        family_id="izmir_empty",
        kind=BlueprintKind.EMPTY_RESULT,
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=BUSES, arguments={"stop_id": literal(STOP_EMPTY)}),
        ),
    )
    findings = list(ExecutionValidator().check(_subject(env, blueprint)))
    assert findings == []


def test_kullanilamaz_trace_reddedilir(env: Environment) -> None:
    """Boş sonuca referans veren blueprint bir plan hatasıdır."""
    blueprint = make_blueprint(
        blueprint_id="izmir_bad_ref_001",
        family_id="izmir_bad_ref",
        available_tools=ALL_TOOLS,
        expected_actions=(
            ExpectedAction(tool_id=SEARCH, arguments={"q": literal("elektrikli scooter")}),
            ExpectedAction(
                tool_id=METADATA,
                arguments={"dataset_id": StepRefArg(step_index=0, path="result.results[0].name")},
            ),
        ),
    )
    result = build_default_pipeline().run(_subject(env, blueprint))
    assert not result.accepted
    assert any("unusable_trace" in f.code for f in result.errors)


def test_negatif_senaryo_cagri_beklemez(env: Environment) -> None:
    blueprint = make_blueprint(
        blueprint_id="izmir_refuse_v_001",
        family_id="izmir_refuse_v",
        kind=BlueprintKind.SHOULD_REFUSE,
        available_tools=ALL_TOOLS,
        expected_actions=(),
        expected_behavior=ExpectedBehavior(
            decision=Decision.CANNOT_ANSWER,
            unsupported_reason_tr="Bu portalda hava durumu tahmini yok.",
            assistant_response_tr="Bu araçlarla hava durumu tahmini sağlayamıyorum.",
        ),
    )
    result = build_default_pipeline().run(_subject(env, blueprint))
    assert result.accepted


# ---------------------------------------------------------------------------
# PII -- cassette gövdeleri düz veri olarak geçirilir (katman kuralı)
# ---------------------------------------------------------------------------


def _valid_tckn(prefix: str = "123456789") -> str:
    """Checksum-geçerli bir TCKN'yi **çalışma anında** üretir.

    Literal olarak yazılsaydı depoda gerçek bir kişinin kimlik numarasına
    denk gelebilecek bir sayı bulunurdu.
    """
    numbers = [int(char) for char in prefix]
    tenth = (sum(numbers[0::2]) * 7 - sum(numbers[1::2])) % 10
    return f"{prefix}{tenth}{(sum(numbers) + tenth) % 10}"


def test_cassette_govdesi_de_taranir(env: Environment) -> None:
    """Kaynak API'ler kişisel veri sızdırabilir; kayıtlar da taranmalı."""
    subject = _subject(
        env,
        _search_blueprint(),
        cassette_payloads={"sha256:test": {"musteri": {"kimlik": _valid_tckn()}}},
    )
    findings = list(PIIValidator().check(subject))
    assert [f.code for f in findings] == ["real_tckn"]


def test_ucuncu_taraf_referans_numarasi_yanlis_pozitif_uretmez(env: Environment) -> None:
    """Bu yanlış pozitif gerçekten yaşandı.

    İzmir taksi durak tablosundaki bir belediye referans numarası
    (`10861282522`) geçerli bir örneği reddetmişti. Sentetik aralık politikası
    yalnızca **bizim ürettiğimiz** içerik için geçerlidir; üçüncü taraf
    yanıtlarında 11 haneli sayılar sıradandır.
    """
    subject = _subject(
        env,
        _search_blueprint(),
        cassette_payloads={"sha256:test": {"MAHALLEID": "10861282522"}},
    )
    assert list(PIIValidator().check(subject)) == []


def test_temiz_cassette_bulgu_uretmez(env: Environment) -> None:
    subject = _subject(env, _search_blueprint())
    assert list(PIIValidator().check(subject)) == []


def test_pii_bulgusu_maskelenmis_raporlanir(env: Environment) -> None:
    """Bulgunun kendisi de kişisel veridir; rapora ham gitmemeli."""
    tckn = _valid_tckn()
    subject = _subject(
        env, _search_blueprint(), cassette_payloads={"sha256:test": {"kimlik": tckn}}
    )
    findings = list(PIIValidator().check(subject))
    assert findings
    assert tckn not in findings[0].message_tr
    assert "*" in findings[0].message_tr


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


def test_birebir_tekrar_yakalanir() -> None:
    validator = DuplicateValidator()
    first = make_example(example_id="toolcall_tr_open_data_000001")
    second = make_example(example_id="toolcall_tr_open_data_000002")

    first_subject = _example_subject(first)
    assert list(validator.check(first_subject)) == []
    validator.commit(first_subject)
    findings = list(validator.check(_example_subject(second)))
    assert any(f.code == "exact_duplicate" for f in findings)


def test_yakin_tekrar_yakalanir() -> None:
    """LLM'den beş paraphrase istenince virgülle ayrılan beş cümle gelir."""
    validator = DuplicateValidator(max_similarity=0.95)
    base = "12345 numaralı durağa yaklaşan otobüsleri listeler misiniz acaba"

    first_subject = _example_subject(make_example(user_text=base))
    validator.commit(first_subject)
    findings = list(
        validator.check(
            _example_subject(
                make_example(
                    example_id="toolcall_tr_open_data_000002",
                    user_text=base + ",",
                )
            )
        )
    )
    assert any(f.code == "near_duplicate" for f in findings)


def test_normalize_edilmis_tekrar_ayri_kodla_yakalanir() -> None:
    validator = DuplicateValidator(max_similarity=0.95)
    first_subject = _example_subject(make_example(user_text="İzmir durağını bul"))
    validator.commit(first_subject)
    findings = list(
        validator.check(
            _example_subject(
                make_example(
                    example_id="toolcall_tr_open_data_000002",
                    user_text="  izmir   duragini bul  ",
                )
            )
        )
    )
    assert any(f.code == "normalized_duplicate" for f in findings)


def test_farkli_ifade_tekrar_sayilmaz() -> None:
    validator = DuplicateValidator(max_similarity=0.95)
    first_subject = _example_subject(make_example(user_text="Otobüs veri setlerini bul"))
    validator.commit(first_subject)
    findings = list(
        validator.check(
            _example_subject(
                make_example(
                    example_id="toolcall_tr_open_data_000002",
                    user_text="Konak'ta hangi duraklar var, en yakını hangisi?",
                )
            )
        )
    )
    assert findings == []


def test_reset_durumu_temizler() -> None:
    validator = DuplicateValidator()
    example = make_example()
    validator.commit(_example_subject(example))
    validator.reset()
    assert list(validator.check(_example_subject(example))) == []


def test_reddedilen_aday_duplicate_durumunu_zehirlemez() -> None:
    pipeline = ValidationPipeline(
        [DuplicateValidator()],
        blocking=frozenset({"duplicate"}),
    )
    example = make_example(user_text="İstanbul için güncel havayı getir.")
    subject = _example_subject(example)

    first = pipeline.run(subject, commit=False)
    second = pipeline.run(subject, commit=False)

    assert first.accepted
    assert second.accepted

    pipeline.commit(subject)
    duplicate = pipeline.run(subject, commit=False)
    assert not duplicate.accepted
    assert any(finding.code == "exact_duplicate" for finding in duplicate.errors)
