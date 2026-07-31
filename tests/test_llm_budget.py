from __future__ import annotations

from typing import Any

import pytest

from toolcall_tr.llm.base import LLMMessage, LLMResponse
from toolcall_tr.llm.budget import (
    BudgetedLLMClient,
    LLMBudgetExceededError,
    LLMBudgetLimits,
    LLMBudgetTracker,
)
from toolcall_tr.llm.openai_client import StructuredOutputError


class _Client:
    provider = "openai"
    model = "gpt-4.1-mini"

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        return _response()

    def complete_json(self, *args, **kwargs) -> LLMResponse:
        return _response()


def _response(*, input_tokens: int = 10, output_tokens: int = 5, cached: bool = False):
    return LLMResponse(
        text="örnek",
        model="gpt-4.1-mini",
        provider="openai",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached=cached,
    )


def test_butce_gercek_kullanimi_raporlar() -> None:
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(max_requests=2, max_input_tokens=100, max_output_tokens=50)
    )
    tracker.before_request()
    tracker.record(_response(cached=True))

    assert tracker.report() == {
        "requests": 1,
        "cached_requests": 1,
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": 0,
        "max_requests": 2,
        "max_input_tokens": 100,
        "max_output_tokens": 50,
    }


def test_istek_butcesi_cagridan_once_durdurur() -> None:
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(max_requests=1, max_input_tokens=100, max_output_tokens=50)
    )
    tracker.before_request()

    with pytest.raises(LLMBudgetExceededError, match="istek bütçesi"):
        tracker.before_request()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response(input_tokens=101), "girdi token"),
        (_response(output_tokens=51), "çıktı token"),
    ],
)
def test_token_butcesi_asimini_durdurur(
    response: LLMResponse, message: str
) -> None:
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(max_requests=2, max_input_tokens=100, max_output_tokens=50)
    )
    tracker.before_request()

    with pytest.raises(LLMBudgetExceededError, match=message):
        tracker.record(response)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_requests": 0, "max_input_tokens": 1, "max_output_tokens": 1},
        {"max_requests": 1, "max_input_tokens": 0, "max_output_tokens": 1},
        {"max_requests": 1, "max_input_tokens": 1, "max_output_tokens": 0},
    ],
)
def test_gecersiz_butce_reddedilir(limits: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        LLMBudgetLimits(**limits)


def test_butceli_istemci_duz_ve_structured_cagrilari_sayar() -> None:
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(max_requests=2, max_input_tokens=100, max_output_tokens=50)
    )
    client = BudgetedLLMClient(_Client(), tracker)
    messages = [LLMMessage(role="user", content="yeniden yaz")]

    client.complete(messages)
    client.complete_json(
        messages,
        schema={"type": "object"},
        schema_name="test",
    )

    assert tracker.requests == 2
    assert tracker.input_tokens == 20
    assert tracker.output_tokens == 10


def test_structured_output_hatasi_da_gercek_token_kullanimini_sayar() -> None:
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(max_requests=2, max_input_tokens=100, max_output_tokens=50)
    )
    failed = _response(input_tokens=17, output_tokens=13)

    class _FailingClient(_Client):
        def complete_json(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise StructuredOutputError("boş structured output", response=failed)

    client = BudgetedLLMClient(_FailingClient(), tracker)

    with pytest.raises(StructuredOutputError, match="boş structured output"):
        client.complete_json(
            [LLMMessage(role="user", content="değerlendir")],
            schema={"type": "object"},
            schema_name="judge",
        )

    assert tracker.requests == 1
    assert tracker.input_tokens == 17
    assert tracker.output_tokens == 13
