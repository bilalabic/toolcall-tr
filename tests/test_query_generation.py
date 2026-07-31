from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.factories import literal, make_blueprint
from toolcall_tr.generation import (
    TEMPLATE_FRAMES,
    LLMQueryGenerator,
    TemplateCapacityExceededError,
    TemplateQueryGenerator,
)
from toolcall_tr.llm import LLMCache, LLMResponse
from toolcall_tr.models import ExpectedAction


def _blueprint():
    return make_blueprint(
        blueprint_id="currency_canary_query_001",
        family_id="currency_canary_query",
        domain="currency",
        provider="frankfurter_ecb",
        available_tools=("currency.get_exchange_rate",),
        utterances=(
            "TRY/EUR referans kurunu getir.",
            "Bir TRY kaç EUR ediyor?",
        ),
        known_information={"base": "TRY", "quote": "EUR"},
        expected_actions=(
            ExpectedAction(
                tool_id="currency.get_exchange_rate",
                arguments={
                    "base": literal("TRY"),
                    "quote": literal("EUR"),
                },
            ),
        ),
    )


def test_template_generator_yuksek_varyantta_benzersizdir() -> None:
    generator = TemplateQueryGenerator()
    blueprint = _blueprint()
    count = len(TEMPLATE_FRAMES) * len(blueprint.utterances)

    generated = [
        generator.generate(blueprint, variant_index=index, root_seed=20260728)
        for index in range(count)
    ]

    assert len({item.text for item in generated}) == count
    assert all("TRY" in item.text and "EUR" in item.text for item in generated)


def test_template_generator_kapasite_dolunca_tekrar_uretmez() -> None:
    generator = TemplateQueryGenerator()
    blueprint = _blueprint()
    capacity = generator.capacity(blueprint)

    with pytest.raises(TemplateCapacityExceededError, match="şablon kapasitesi"):
        generator.generate(blueprint, variant_index=capacity, root_seed=20260728)


def test_template_generator_deterministiktir() -> None:
    generator = TemplateQueryGenerator()
    blueprint = _blueprint()

    first = generator.generate(blueprint, variant_index=37, root_seed=42)
    second = generator.generate(blueprint, variant_index=37, root_seed=42)

    assert first == second


def test_canary_modu_yalniz_dogrulanmis_ana_ifadeyi_cerceveler() -> None:
    generator = TemplateQueryGenerator(cycle_utterances=False)
    blueprint = _blueprint()

    generated = [
        generator.generate(blueprint, variant_index=index, root_seed=42)
        for index in range(len(TEMPLATE_FRAMES))
    ]

    assert len({item.text for item in generated}) == len(TEMPLATE_FRAMES)
    assert all("referans kurunu getir" in item.text for item in generated)


class _StructuredClient:
    provider = "openai"
    model = "gpt-4.1-mini"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages: list[object] = []

    def complete_json(self, messages: object, **kwargs: Any) -> LLMResponse:
        self.messages.append(messages)
        self.calls.append(kwargs)
        return LLMResponse(
            text=(
                '{"query":"TRY/EUR kurunu öğrenebilir miyim?",'
                '"reasoning_summary_tr":"Kullanıcı TRY/EUR kurunu soruyor; '
                'gerekli iki para birimi de mesajda mevcut."}'
            ),
            provider=self.provider,
            model=self.model,
            input_tokens=40,
            output_tokens=9,
            cached_input_tokens=12,
        )


def test_llm_generator_strict_json_query_ve_provenance_uretir() -> None:
    client = _StructuredClient()
    generator = LLMQueryGenerator(
        client,  # type: ignore[arg-type]
        system_prompt="Anlamı koruyarak yeniden yaz.",
        temperature=0.7,
        max_tokens=222,
    )

    generated = generator.generate(_blueprint(), variant_index=0, root_seed=42)

    assert generated.text == "TRY/EUR kurunu öğrenebilir miyim?"
    assert generated.usage is not None
    assert generated.usage.model == "gpt-4.1-mini"
    assert generated.usage.cached_input_tokens == 12
    assert generated.reasoning_summary_tr == (
        "Kullanıcı TRY/EUR kurunu soruyor; gerekli iki para birimi de mesajda mevcut."
    )
    assert client.calls[0]["schema_name"] == "toolcall_tr_user_query_v6"
    assert client.calls[0]["temperature"] == 0.7
    assert client.calls[0]["max_tokens"] == 222


def test_generator_cache_blueprint_icerigi_degistiginde_gecersizlesir(tmp_path: Path) -> None:
    client = _StructuredClient()
    generator = LLMQueryGenerator(
        client,  # type: ignore[arg-type]
        system_prompt="Blueprint'ten soru üret.",
        cache=LLMCache(tmp_path / "cache"),
    )
    original = _blueprint()
    changed = original.model_copy(update={"user_goal": "TRY/EUR kur bilgisini kısaca öğrenmek"})

    generator.generate(original, variant_index=0, root_seed=42)
    generator.generate(original, variant_index=0, root_seed=42)
    generator.generate(changed, variant_index=0, root_seed=42)

    assert len(client.calls) == 2


def test_user_message_kaynakli_action_degeri_promptta_korunur() -> None:
    client = _StructuredClient()
    generator = LLMQueryGenerator(
        client,  # type: ignore[arg-type]
        system_prompt="Blueprint'ten soru üret.",
    )
    blueprint = _blueprint().model_copy(update={"known_information": {"base": "TRY"}})

    generator.generate(blueprint, variant_index=0, root_seed=42)

    messages = client.messages[0]
    assert isinstance(messages, list)
    assert "EUR" in messages[1].content
    assert "veritabanı/tablo/veri seti kataloğu" in messages[1].content
    assert "sipariş/fatura/ön muhasebe" in messages[1].content


def test_judge_reti_sonraki_soru_uretimine_onarim_notu_olarak_verilir() -> None:
    client = _StructuredClient()
    generator = LLMQueryGenerator(
        client,  # type: ignore[arg-type]
        system_prompt="Blueprint'ten soru üret.",
        cache=None,
    )

    generator.generate(
        _blueprint(),
        variant_index=1,
        root_seed=42,
        repair_feedback=(
            "openai_semantic_policy_judge/semantic_mismatch: ek amaç üretildi",
        ),
    )

    messages = client.messages[0]
    assert isinstance(messages, list)
    assert "Önceki aday" in messages[1].content
    assert "semantic_mismatch" in messages[1].content
    assert "sabit değerlerini değiştirme" in messages[1].content


def test_onarim_geri_bildirimi_cache_anahtarini_ayirir(tmp_path: Path) -> None:
    client = _StructuredClient()
    generator = LLMQueryGenerator(
        client,  # type: ignore[arg-type]
        system_prompt="Blueprint'ten soru üret.",
        cache=LLMCache(tmp_path / "cache"),
    )
    blueprint = _blueprint()

    generator.generate(blueprint, variant_index=1, root_seed=42)
    generator.generate(
        blueprint,
        variant_index=1,
        root_seed=42,
        repair_feedback=("language_not_turkish: Türkçe değil",),
    )

    assert len(client.calls) == 2
