"""LLM istemcileri — sahte istemci nesnesiyle, ağa çıkmadan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from toolcall_tr.llm import LLMMessage, build_client
from toolcall_tr.llm.openai_client import (
    DEFAULT_MODEL,
    OpenAIClient,
    StructuredOutputError,
)


@dataclass
class _FakeInputDetails:
    cached_tokens: int = 80


@dataclass
class _FakeUsage:
    input_tokens: int = 120
    output_tokens: int = 18
    input_tokens_details: _FakeInputDetails = field(default_factory=_FakeInputDetails)


@dataclass
class _FakeIncompleteDetails:
    reason: str


@dataclass
class _FakeOutputDetails:
    reasoning_tokens: int = 0


@dataclass
class _FakeResponse:
    output_text: str = "  Otobüs duraklarıyla ilgili veri var mı?  "
    usage: _FakeUsage = field(default_factory=_FakeUsage)
    status: str = "completed"
    incomplete_details: _FakeIncompleteDetails | None = None
    output: list[Any] = field(default_factory=list)


class _FakeResponses:
    """Responses API çağrılarını kaydeder; istenirse bir parametreyi reddeder."""

    def __init__(
        self,
        *,
        output_text: str = "  Otobüs duraklarıyla ilgili veri var mı?  ",
        unsupported: tuple[str, ...] = (),
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.output_text = output_text
        self.unsupported = unsupported

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        for parameter in self.unsupported:
            if parameter in kwargs:
                raise ValueError(
                    f"Error code: 400 - Unsupported parameter: '{parameter}' "
                    "is not supported with this model."
                )
        return _FakeResponse(output_text=self.output_text)


class _FakeClient:
    """Ağa çıkmayan sahte OpenAI istemcisi."""

    def __init__(
        self,
        *,
        output_text: str = "  Otobüs duraklarıyla ilgili veri var mı?  ",
        unsupported: tuple[str, ...] = (),
    ) -> None:
        self.responses = _FakeResponses(output_text=output_text, unsupported=unsupported)


@pytest.fixture
def fake() -> _FakeClient:
    return _FakeClient()


def _messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Sen Türkçe konuşan bir kullanıcısın."),
        LLMMessage(role="user", content="Cümleyi yeniden yaz."),
    ]


def test_responses_api_kullanilir_ve_yanit_kirpilir(fake: _FakeClient) -> None:
    response = OpenAIClient("gpt-5.6-luna", client=fake).complete(_messages())

    assert response.text == "Otobüs duraklarıyla ilgili veri var mı?"
    assert response.provider == "openai"
    assert response.model == "gpt-5.6-luna"
    assert response.metadata["api"] == "responses"
    assert len(fake.responses.calls) == 1


def test_token_sayaclari_tasinir(fake: _FakeClient) -> None:
    response = OpenAIClient("gpt-5.6-luna", client=fake).complete(_messages())

    assert response.input_tokens == 120
    assert response.output_tokens == 18
    assert response.cached_input_tokens == 80
    assert response.cached is False


def test_responses_payload_guvenli_ve_mesajlari_korur(fake: _FakeClient) -> None:
    OpenAIClient("gpt-5.6-luna", client=fake).complete(_messages(), max_tokens=256)
    payload = fake.responses.calls[0]

    assert payload["store"] is False
    assert payload["max_output_tokens"] == 256
    assert payload["input"][0]["role"] == "system"
    assert len(payload["input"]) == 2
    assert "messages" not in payload
    assert "max_completion_tokens" not in payload


def test_reasoning_verbosity_ve_safety_identifier_gonderilir(fake: _FakeClient) -> None:
    client = OpenAIClient(
        "gpt-5.6-sol",
        client=fake,
        reasoning_effort="high",
        verbosity="low",
        safety_identifier="sha256:anonim-kullanici",
    )
    client.complete(_messages())
    payload = fake.responses.calls[0]

    assert payload["reasoning"] == {"effort": "high"}
    assert payload["text"] == {"verbosity": "low"}
    assert payload["safety_identifier"] == "sha256:anonim-kullanici"


def test_cagri_ayarlari_constructor_varsayilanini_gecersiz_kilar(fake: _FakeClient) -> None:
    client = OpenAIClient(
        "gpt-5.6-terra",
        client=fake,
        reasoning_effort="low",
        verbosity="high",
    )
    client.complete(_messages(), reasoning_effort="xhigh", verbosity="low")
    payload = fake.responses.calls[0]

    assert payload["reasoning"] == {"effort": "xhigh"}
    assert payload["text"] == {"verbosity": "low"}


def test_desteklenmeyen_temperature_dusurulur_ve_hatirlanir() -> None:
    fake = _FakeClient(unsupported=("temperature",))
    client = OpenAIClient("gpt-5.6-luna", client=fake)

    response = client.complete(_messages(), temperature=0.0)
    first_call_count = len(fake.responses.calls)
    client.complete(_messages())

    assert response.text
    assert first_call_count == 2
    assert "temperature" not in fake.responses.calls[-1]
    assert len(fake.responses.calls) == 3


def test_tanimadigi_hata_yutulmaz(fake: _FakeClient) -> None:
    def explode(**kwargs: Any) -> None:
        raise ValueError("Error code: 401 - Incorrect API key provided")

    fake.responses.create = explode  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="401"):
        OpenAIClient("gpt-5.6-luna", client=fake).complete(_messages())


def test_structured_output_strict_schema_ile_gonderilir() -> None:
    fake = _FakeClient(output_text='{"score": 4, "accepted": true}')
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "accepted": {"type": "boolean"},
        },
        "required": ["score", "accepted"],
        "additionalProperties": False,
    }

    response = OpenAIClient("gpt-5.6-sol", client=fake).complete_json(
        _messages(),
        schema=schema,
        schema_name="quality_judge",
        reasoning_effort="high",
    )
    payload = fake.responses.calls[0]

    assert response.text == '{"score": 4, "accepted": true}'
    assert payload["store"] is False
    assert payload["text"]["format"] == {
        "type": "json_schema",
        "name": "quality_judge",
        "schema": schema,
        "strict": True,
    }
    assert payload["reasoning"] == {"effort": "high"}


@pytest.mark.parametrize(
    ("output_text", "message"),
    [
        ("JSON değil", "geçerli JSON değil"),
        ('{"score": "yüksek"}', "JSON Schema ile uyuşmuyor"),
    ],
)
def test_structured_output_yerelde_dogrulanir(output_text: str, message: str) -> None:
    fake = _FakeClient(output_text=output_text)
    schema = {
        "type": "object",
        "properties": {"score": {"type": "integer"}},
        "required": ["score"],
        "additionalProperties": False,
    }

    with pytest.raises(StructuredOutputError, match=message):
        OpenAIClient("gpt-5.6-sol", client=fake).complete_json(
            _messages(), schema=schema, schema_name="judge"
        )


def test_incomplete_structured_output_nedeni_ve_kullanimi_korur(
    fake: _FakeClient,
) -> None:
    response = _FakeResponse(
        output_text="",
        status="incomplete",
        incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
    )
    response.usage.output_tokens_details = _FakeOutputDetails(  # type: ignore[attr-defined]
        reasoning_tokens=18
    )
    fake.responses.create = lambda **kwargs: response  # type: ignore[method-assign]

    with pytest.raises(
        StructuredOutputError,
        match=r"status=incomplete; neden=max_output_tokens",
    ) as captured:
        OpenAIClient("gpt-5-mini", client=fake).complete_json(
            _messages(),
            schema={"type": "object"},
            schema_name="judge",
        )

    assert captured.value.response is not None
    assert captured.value.response.output_tokens == 18
    assert captured.value.response.metadata == {
        "api": "responses",
        "status": "incomplete",
        "incomplete_reason": "max_output_tokens",
        "reasoning_tokens": "18",
    }


def test_completed_bos_structured_output_acik_hata_verir(fake: _FakeClient) -> None:
    fake.responses.create = lambda **kwargs: _FakeResponse(  # type: ignore[method-assign]
        output_text="",
        status="completed",
    )

    with pytest.raises(StructuredOutputError, match=r"boş döndü; status=completed"):
        OpenAIClient("gpt-5-mini", client=fake).complete_json(
            _messages(),
            schema={"type": "object"},
            schema_name="judge",
        )


def test_refusal_structured_output_olarak_kabul_edilmez(fake: _FakeClient) -> None:
    fake.responses.create = lambda **kwargs: _FakeResponse(  # type: ignore[method-assign]
        output_text="",
        status="completed",
        output=[
            {
                "type": "message",
                "content": [
                    {
                        "type": "refusal",
                        "refusal": "Bu isteği değerlendiremiyorum.",
                    }
                ],
            }
        ],
    )

    with pytest.raises(StructuredOutputError, match="model tarafından reddedildi") as captured:
        OpenAIClient("gpt-5-mini", client=fake).complete_json(
            _messages(),
            schema={"type": "object"},
            schema_name="judge",
        )

    assert captured.value.response is not None
    assert (
        captured.value.response.metadata["refusal"]
        == "Bu isteği değerlendiremiyorum."
    )


def test_gecersiz_schema_apiye_gonderilmez(fake: _FakeClient) -> None:
    with pytest.raises(ValueError, match="geçersiz JSON Schema"):
        OpenAIClient("gpt-5.6-sol", client=fake).complete_json(
            _messages(),
            schema={"type": "bilinmeyen-tip"},
            schema_name="judge",
        )
    assert fake.responses.calls == []


def test_gecersiz_schema_adi_apiye_gonderilmez(fake: _FakeClient) -> None:
    with pytest.raises(ValueError, match="schema_name"):
        OpenAIClient("gpt-5.6-sol", client=fake).complete_json(
            _messages(),
            schema={"type": "object"},
            schema_name="../judge",
        )
    assert fake.responses.calls == []


def test_varsayilan_model_paraphrase_katmanindan() -> None:
    assert DEFAULT_MODEL == "gpt-4.1-mini"


def test_api_anahtari_yanitta_ve_payloadta_tasinmaz(fake: _FakeClient) -> None:
    response = OpenAIClient(
        "gpt-5.6-luna", api_key="gizli-anahtar", client=fake
    ).complete(_messages())
    serialized = f"{response.text}{response.metadata}{response.model}{response.provider}"

    assert "gizli-anahtar" not in serialized
    assert "gizli-anahtar" not in str(fake.responses.calls)


def test_anahtar_yoksa_gurultulu_patlar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises((ValueError, RuntimeError), match=r"OPENAI_API_KEY|openai paketi"):
        OpenAIClient("gpt-5.6-luna")


def test_bilinmeyen_saglayici_reddedilir() -> None:
    with pytest.raises(ValueError, match="bilinmeyen LLM sağlayıcı"):
        build_client("bilinmeyen-saglayici")
