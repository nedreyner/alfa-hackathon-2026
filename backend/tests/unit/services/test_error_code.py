from __future__ import annotations

from alfa_insight.errors import BudgetExceeded, LLMReplayMiss, LLMUnavailable
from alfa_insight.services.jobs import error_code


def test_error_codes_for_client() -> None:
    assert error_code(TimeoutError()) == "timeout"
    assert error_code(LLMUnavailable("нет")) == "llm_unavailable"
    # replay без ответа в кеше — для клиента «сервис аналитики недоступен», а не внутренняя ошибка
    assert error_code(LLMReplayMiss("нет в кеше")) == "llm_unavailable"
    assert error_code(BudgetExceeded("day")) == "budget_exhausted"
    assert error_code(RuntimeError("x")) == "internal"
