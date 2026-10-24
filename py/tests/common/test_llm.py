"""LLM services (D-137): priority order, keys, cooldowns, daily limits, cost cap, validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, text

from stockhub.common.llm import (
    Completion,
    LLMError,
    LLMRateLimitedError,
    LLMRouter,
    LLMService,
    LLMUnavailableError,
    NoLLMServiceError,
    OpenAICompatibleClient,
    check_service,
    extract_json,
)

NOW = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)  # 10:00 Taipei
KEYS = {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "q", "OPENROUTER_API_KEY": "o"}


class Answer(BaseModel):
    value: int


class FakeClient:
    """Answers per service code: a string (the content) or an exception to raise."""

    def __init__(self, script: dict[str, list[str | Exception]]) -> None:
        self.script = script
        self.calls: list[str] = []

    def complete(
        self, service: LLMService, api_key: str, system: str, user: str, schema: dict[str, Any]
    ) -> Completion:
        self.calls.append(service.code)
        outcome = self.script[service.code].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Completion(outcome, 100, 20)


def _router(engine: Engine, client: FakeClient, env: dict[str, str] | None = None) -> LLMRouter:
    return LLMRouter(
        engine,
        client,
        env=KEYS if env is None else env,
        clock=lambda: NOW,
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
    )


def _provider(engine: Engine, code: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT p.cooldown_until, p.last_error, p.last_success_at, u.requests, "
                "u.failures, u.input_tokens, u.output_tokens, u.cost_usd FROM llm_providers p "
                "LEFT JOIN llm_usage u ON u.provider_id = p.id WHERE p.code = :c"
            ),
            {"c": code},
        ).one()
    return dict(row._mapping)


def test_extract_json() -> None:
    assert extract_json('{"value": 1}') == '{"value": 1}'
    assert extract_json('<think>hmm {"x":0}</think>\n```json\n{"value": 2}\n```') == '{"value": 2}'
    assert extract_json('答案如下：{"value": 3} 以上') == '{"value": 3}'
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_first_service_with_a_key_answers_and_usage_is_recorded(clean_db: Engine) -> None:
    client = FakeClient({"google_ai_studio": ['{"value": 7}']})
    answer = _router(clean_db, client).ask("sys", "user", Answer)
    assert answer.value == Answer(value=7)
    assert answer.service.code == "google_ai_studio"
    assert client.calls == ["google_ai_studio"]
    state = _provider(clean_db, "google_ai_studio")
    assert state["requests"] == 1
    assert state["failures"] == 0
    assert (state["input_tokens"], state["output_tokens"]) == (100, 20)
    assert state["cost_usd"] == Decimal(0)
    assert state["last_success_at"] == NOW


def test_failover_rests_rate_limited_and_rejected_services(clean_db: Engine) -> None:
    client = FakeClient(
        {
            "google_ai_studio": [LLMRateLimitedError("429", retry_after=120)],
            "groq": [LLMUnavailableError("HTTP 404 model")],
            "openrouter": ['{"value": 1}'],
        }
    )
    answer = _router(clean_db, client).ask("sys", "user", Answer)
    assert answer.service.code == "openrouter"
    assert client.calls == ["google_ai_studio", "groq", "openrouter"]
    google, groq = _provider(clean_db, "google_ai_studio"), _provider(clean_db, "groq")
    assert google["cooldown_until"] == NOW + timedelta(seconds=120)
    assert google["failures"] == 1
    assert groq["cooldown_until"] == NOW + timedelta(hours=6)
    assert "404" in groq["last_error"]
    # Resting services are skipped next time; NVIDIA has no key in this environment.
    later = FakeClient({"openrouter": ['{"value": 2}']})
    assert _router(clean_db, later).ask("s", "u", Answer).value.value == 2
    assert later.calls == ["openrouter"]


def test_invalid_answers_fail_over_and_a_streak_rests_the_service(clean_db: Engine) -> None:
    client = FakeClient(
        {
            "google_ai_studio": ['{"value": "x"}', "nope", '{"oops": 1}'],
            "groq": ['{"value": 3}', '{"value": 4}', '{"value": 5}'],
        }
    )
    router = _router(clean_db, client)
    for expected in (3, 4, 5):
        assert router.ask("s", "u", Answer).value.value == expected
    google = _provider(clean_db, "google_ai_studio")
    assert google["failures"] == 3
    assert google["cooldown_until"] == NOW + timedelta(minutes=15)
    assert google["last_error"].startswith("invalid answer from google_ai_studio")


def test_daily_request_limit_and_no_service(clean_db: Engine) -> None:
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO llm_usage (provider_id, usage_date, requests) "
                "SELECT id, '2026-10-26', 200 FROM llm_providers WHERE code = 'google_ai_studio'"
            )
        )
    client = FakeClient({"groq": ['{"value": 1}']})
    assert _router(clean_db, client).ask("s", "u", Answer).service.code == "groq"
    with pytest.raises(NoLLMServiceError, match="no LLM service available"):
        _router(clean_db, FakeClient({}), env={}).ask("s", "u", Answer)
    failing = FakeClient({"groq": [LLMError("boom")], "openrouter": [LLMError("bang")]})
    with pytest.raises(NoLLMServiceError, match="boom; bang"):
        _router(clean_db, failing).ask("s", "u", Answer)


def test_paid_services_need_the_daily_cost_cap(clean_db: Engine) -> None:
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE llm_providers SET enabled = false"))
        conn.execute(
            text(
                "INSERT INTO llm_providers (code, name, base_url, model, api_key_env, priority, "
                "paid, input_usd_per_mtok, output_usd_per_mtok) VALUES ('paid', 'Paid', "
                "'https://paid.example/v1', 'm', 'PAID_KEY', 5, true, 1, 5)"
            )
        )
    env = {"PAID_KEY": "k"}
    with pytest.raises(NoLLMServiceError):
        _router(clean_db, FakeClient({}), env=env).ask("s", "u", Answer)
    with clean_db.begin() as conn:
        conn.execute(
            text("INSERT INTO settings (key, value) VALUES ('news', '{\"llmDailyUsdCap\": 0.01}')")
        )
    client = FakeClient({"paid": ['{"value": 1}']})
    assert _router(clean_db, client, env=env).ask("s", "u", Answer).value.value == 1
    # 100 input + 20 output tokens at $1 / $5 per million.
    assert _provider(clean_db, "paid")["cost_usd"] == Decimal("0.000200")


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


SERVICE = LLMService(
    id=1,
    code="groq",
    name="Groq",
    base_url="https://api.groq.com/openai/v1/",
    model="qwen/qwen3-32b",
    api_key_env="GROQ_API_KEY",
    priority=1,
    paid=False,
    requests_per_minute=None,
    requests_per_day=None,
    json_mode="json_object",
    input_usd_per_mtok=None,
    output_usd_per_mtok=None,
    cooldown_until=None,
)


def test_openai_compatible_request_and_errors() -> None:
    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value": 1}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    client = OpenAICompatibleClient(_http(ok))
    completion = client.complete(SERVICE, "secret", "sys", "user", {})
    assert completion == Completion('{"value": 1}', 11, 3)
    request = seen[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "qwen/qwen3-32b"
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]

    def status(code: int, headers: dict[str, str] | None = None) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(_http(lambda _: httpx.Response(code, headers=headers)))

    with pytest.raises(LLMRateLimitedError) as limited:
        status(429, {"retry-after": "30"}).complete(SERVICE, "k", "s", "u", {})
    assert limited.value.retry_after == 30
    with pytest.raises(LLMUnavailableError):
        status(401).complete(SERVICE, "k", "s", "u", {})
    with pytest.raises(LLMError):
        status(503).complete(SERVICE, "k", "s", "u", {})
    with pytest.raises(LLMError, match="unexpected answer"):
        OpenAICompatibleClient(_http(lambda _: httpx.Response(200, json={}))).complete(
            SERVICE, "k", "s", "u", {}
        )


def test_check_service_lists_models() -> None:
    def models(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "qwen/qwen3-32b"}, {"id": "x"}]})

    assert check_service(SERVICE, "k", _http(models)) == (True, "可用（2 個模型）")
    missing = LLMService(**{**SERVICE.__dict__, "model": "gone"})
    ok, message = check_service(missing, "k", _http(models))
    assert not ok
    assert "找不到模型 gone" in message
    assert check_service(SERVICE, "k", _http(lambda _: httpx.Response(401)))[0] is False
