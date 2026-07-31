"""Dışa aktarım biçimleri.

En önemli test `test_canonical_round_trip`: canonical veri **kayıpsız**
olmalı. Exporter'lar birer görünümdür; iç gösterimi belirlemezler.
"""

from __future__ import annotations

import json

import pytest

from tests.factories import make_example
from toolcall_tr.models import (
    BlueprintKind,
    Decision,
    Example,
    GroundTruth,
    Message,
    MessageRole,
    Scenario,
)
from toolcall_tr.serialize import (
    EXPORTERS,
    to_canonical_jsonl,
    to_openai,
    to_openai_call_only,
    to_openai_trajectory,
    to_sharegpt,
    to_xlam,
)


def test_canonical_round_trip() -> None:
    """JSONL'e yazıp geri yüklemek örneği birebir korumalı."""
    original = make_example()
    line = to_canonical_jsonl([original]).strip()
    restored = Example.model_validate(json.loads(line))
    assert restored == original


def test_canonical_jsonl_deterministik() -> None:
    example = make_example()
    assert to_canonical_jsonl([example]) == to_canonical_jsonl([example])


def test_canonical_jsonl_turkce_karakterleri_kacislamaz() -> None:
    line = to_canonical_jsonl([make_example(user_text="Otobüs durağı nerede?")])
    assert "Otobüs durağı" in line


@pytest.mark.parametrize("name", sorted(EXPORTERS))
def test_exporter_canonical_veriyi_degistirmez(name: str) -> None:
    """Dışa aktarım bir okuma işlemidir; kaynağı bozmamalı."""
    example = make_example()
    before = example.model_dump(mode="json")
    EXPORTERS[name](example)
    assert example.model_dump(mode="json") == before


@pytest.mark.parametrize("name", sorted(EXPORTERS))
def test_exporter_ciktisi_json_serilestirilebilir(name: str) -> None:
    payload = EXPORTERS[name](make_example())
    json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def test_openai_bicimi() -> None:
    payload = to_openai(make_example())
    assert payload["messages"][0]["role"] == "user"
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "search_datasets"
    # `additionalProperties: false` korunmalı: bilinmeyen parametre üretmek
    # sıfır toleranslı bir hatadır.
    assert payload["tools"][0]["function"]["parameters"]["additionalProperties"] is False


def test_openai_tool_call_argumanlari_string() -> None:
    """OpenAI şemasında `arguments` bir JSON string'tir."""
    payload = to_openai(make_example())
    assistant = next(m for m in payload["messages"] if m["role"] == "assistant")
    arguments = assistant["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"q": "otobüs"}


def test_openai_yan_alan_split_tasir() -> None:
    """`split` ve `family_id` sohbet şemasına sığmaz; kaybolmamalı."""
    payload = to_openai(make_example())
    assert payload["toolcall_tr"]["split"] == "train"
    assert payload["toolcall_tr"]["family_id"] == "izmir_dataset_search"


def test_exporter_kisa_gerekceyi_thinking_uyumluluk_alaniyla_tasir() -> None:
    example = make_example(
        reasoning_summary_tr=(
            "Kullanıcı otobüs verisi arıyor; arama aracı bu bilgi ihtiyacına uygundur."
        )
    )

    for exporter in EXPORTERS.values():
        sidecar = exporter(example)["toolcall_tr"]
        assert sidecar["reasoning_summary_tr"] == example.reasoning_summary_tr
        assert sidecar["thinking"] == example.reasoning_summary_tr


@pytest.mark.parametrize(
    ("decision", "kind", "response"),
    [
        (
            Decision.CLARIFICATION,
            BlueprintKind.SHOULD_ASK_CLARIFICATION,
            "Hangi durak için bakmamı istersiniz? Lütfen durak numarasını paylaşın.",
        ),
        (
            Decision.DIRECT_ANSWER,
            BlueprintKind.SHOULD_ANSWER_DIRECTLY,
            "Bir yılda 12 ay vardır.",
        ),
        (
            Decision.CANNOT_ANSWER,
            BlueprintKind.SHOULD_REFUSE,
            "Bu işlemi mevcut araçlarla gerçekleştiremiyorum.",
        ),
    ],
)
def test_no_call_kararlari_exportta_gercek_asistan_hedefi_tasir(
    decision: Decision,
    kind: BlueprintKind,
    response: str,
) -> None:
    missing_parameters = ("stop_id",) if decision is Decision.CLARIFICATION else ()
    example = make_example(
        scenario=Scenario(
            decision=decision,
            kind=kind,
            interaction_type="single_turn",
            difficulty="easy",
            expected_result="no_call",
        ),
        messages=(
            Message(role=MessageRole.USER, content="Yardım eder misin?"),
            Message(role=MessageRole.ASSISTANT, content=response),
        ),
        ground_truth=GroundTruth(
            calls=(),
            missing_parameters=missing_parameters,
            response_intent_tr="Uygun no-call yanıtını ver.",
            assistant_response_tr=response,
        ),
    )

    openai_payload = to_openai(example)
    assert openai_payload["messages"][-1] == {
        "role": "assistant",
        "content": response,
    }

    sharegpt_payload = to_sharegpt(example)
    assert sharegpt_payload["conversations"][-1] == {
        "from": "gpt",
        "value": response,
    }

    xlam_payload = to_xlam(example)
    assert json.loads(xlam_payload["answers"]) == []
    assert xlam_payload["toolcall_tr"]["assistant_response_tr"] == response


def test_tool_call_tam_trajectory_gozleme_dayali_final_cevap_tasir() -> None:
    example = make_example()

    assert example.ground_truth.assistant_response_tr is None
    assert example.ground_truth.final_response_source == "terminal_observation"
    openai_payload = to_openai_trajectory(example)
    assistant_messages = [
        message for message in openai_payload["messages"] if message["role"] == "assistant"
    ]
    assert len(assistant_messages) == 2
    assert "tool_calls" in assistant_messages[0]
    assert "content" not in assistant_messages[0]
    assert assistant_messages[-1] == {
        "role": "assistant",
        "content": example.ground_truth.final_response_tr,
    }
    assert openai_payload["toolcall_tr"]["trajectory_complete"] is True


def test_call_only_observation_ve_final_cevabi_disarida_birakir() -> None:
    payload = to_openai_call_only(make_example())

    assert [message["role"] for message in payload["messages"]] == [
        "user",
        "assistant",
    ]
    assert "tool_calls" in payload["messages"][-1]
    assert payload["toolcall_tr"]["view"] == "call_only"


def test_eksik_eski_kayit_tam_trajectory_diye_disari_aktarilmaz() -> None:
    complete = make_example()
    legacy = complete.model_copy(
        update={
            "messages": complete.messages[:2],
            "ground_truth": GroundTruth(calls=complete.ground_truth.calls),
        }
    )

    # Geriye uyumlu canonical/OpenAI görünümü eski kaydı hâlâ okuyabilir.
    assert to_openai(legacy)["toolcall_tr"]["trajectory_complete"] is False
    with pytest.raises(ValueError, match="final_response_tr"):
        to_openai_trajectory(legacy)


@pytest.mark.parametrize("name", sorted(EXPORTERS))
def test_exporter_kaynak_ve_lisans_tasir(name: str) -> None:
    payload = EXPORTERS[name](make_example())
    provenance = payload["toolcall_tr"]["provenance"]
    assert provenance["trace_id"].startswith("sha256:")
    assert provenance["sources"][0]["license"] == "CC-BY-4.0"
    assert provenance["sources"][0]["schema_version"] == "2026-07"


# ---------------------------------------------------------------------------
# xLAM
# ---------------------------------------------------------------------------


def test_xlam_bicimi() -> None:
    payload = to_xlam(make_example(user_text="Otobüs veri setlerini bul"))
    assert payload["query"] == "Otobüs veri setlerini bul"
    answers = json.loads(payload["answers"])
    assert answers == [{"name": "search_datasets", "arguments": {"q": "otobüs"}}]


def test_xlam_karari_yan_alanda_tasir() -> None:
    """xLAM şemasında "çağırma" diye bir cevap yok; bilgi kaybolmamalı."""
    payload = to_xlam(make_example())
    assert payload["toolcall_tr"]["decision"] == Decision.TOOL_CALL.value


# ---------------------------------------------------------------------------
# ShareGPT
# ---------------------------------------------------------------------------


def test_sharegpt_rol_esleme() -> None:
    payload = to_sharegpt(make_example())
    roles = [turn["from"] for turn in payload["conversations"]]
    assert roles[0] == "human"
    assert "gpt" in roles


def test_sharegpt_tool_cagrisi_serilestirilir() -> None:
    payload = to_sharegpt(make_example())
    gpt_turn = next(t for t in payload["conversations"] if t["from"] == "gpt")
    assert json.loads(gpt_turn["value"]) == [
        {"name": "search_datasets", "arguments": {"q": "otobüs"}}
    ]
