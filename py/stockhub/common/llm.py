"""LLM services for news summaries and sentiment: free first, any OpenAI-compatible endpoint.

Services are rows of llm_providers (D-137), tried in priority order. A service is skipped
while it has no key in the environment, rests after a 429 or an error streak
(cooldown_until), has used its requests for the Taipei day, or is paid while the daily cost
cap (settings news.llmDailyUsdCap, default 0) is reached. Every answer is validated against
a pydantic model; an answer that does not validate counts as a failure and the next service
is tried. Usage is accumulated per service and day in llm_usage.

Only public text (news, announcements, posts) is ever sent; never holdings.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, text

from stockhub.common.timeutil import taipei_today, utcnow

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(90.0, connect=10.0)
RATE_LIMIT_REST = timedelta(minutes=10)
"""Rest after a 429 without Retry-After (free tiers often mean 'try again later today')."""
UNAVAILABLE_REST = timedelta(hours=6)
"""Rest after a rejected key or an unknown model: needs the user's attention on /admin."""
ERROR_STREAK = 3
ERROR_REST = timedelta(minutes=15)
"""Rest after this many failures in a row (timeouts, 5xx, invalid answers)."""


class LLMError(Exception):
    """One request failed; the next service may still answer."""


class LLMRateLimitedError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMUnavailableError(LLMError):
    """The service cannot answer until the user fixes something (key, model name)."""


class NoLLMServiceError(RuntimeError):
    """No service could answer (none configured, all resting, or all failed)."""


@dataclass(frozen=True)
class LLMService:
    id: int
    code: str
    name: str
    base_url: str
    model: str
    api_key_env: str
    priority: int
    paid: bool
    requests_per_minute: int | None
    requests_per_day: int | None
    json_mode: str
    input_usd_per_mtok: Decimal | None
    output_usd_per_mtok: Decimal | None
    cooldown_until: datetime | None

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        if not self.paid:
            return Decimal(0)
        price_in = self.input_usd_per_mtok or Decimal(0)
        price_out = self.output_usd_per_mtok or Decimal(0)
        return (price_in * input_tokens + price_out * output_tokens) / Decimal(1_000_000)


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class ChatClient(Protocol):
    def complete(
        self,
        service: LLMService,
        api_key: str,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> Completion: ...


_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def extract_json(content: str) -> str:
    """The JSON object in an answer: reasoning (<think>…</think>) and ``` fences removed,
    then the outermost {...}."""
    body = _FENCE.sub("", _THINK.sub("", content).strip()).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("answer has no JSON object")
    return body[start : end + 1]


class OpenAICompatibleClient:
    """POST {base_url}/chat/completions (Google AI Studio, Groq, OpenRouter, NVIDIA NIM...)."""

    def __init__(self, client: httpx.Client | None = None, max_tokens: int = 4096) -> None:
        self.client = client or httpx.Client(timeout=TIMEOUT)
        self.max_tokens = max_tokens

    def complete(
        self,
        service: LLMService,
        api_key: str,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> Completion:
        body: dict[str, Any] = {
            "model": service.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        if service.json_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema, "strict": False},
            }
        elif service.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        try:
            response = self.client.post(
                service.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise LLMError(f"timeout from {service.code}") from exc
        except httpx.TransportError as exc:
            raise LLMError(f"network error from {service.code}: {exc}") from exc
        status = response.status_code
        detail = response.text[:300]
        if status == 429:
            retry = response.headers.get("retry-after")
            seconds = float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
            raise LLMRateLimitedError(f"429 from {service.code}: {detail}", seconds)
        if status in (401, 403, 404):
            raise LLMUnavailableError(f"HTTP {status} from {service.code}: {detail}")
        if status >= 400:
            raise LLMError(f"HTTP {status} from {service.code}: {detail}")
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected answer shape from {service.code}") from exc
        usage = data.get("usage") or {}
        return Completion(
            text=content,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


@dataclass(frozen=True)
class Answer[M: BaseModel]:
    value: M
    service: LLMService
    completion: Completion


class LLMRouter:
    """Tries the enabled services in priority order until one returns a valid answer."""

    def __init__(
        self,
        engine: Engine,
        client: ChatClient | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engine = engine
        self.client = client or OpenAICompatibleClient()
        self.env = env if env is not None else os.environ
        self._clock, self._sleep, self._monotonic = clock, sleep, monotonic
        self._last_call: dict[int, float] = {}
        self._streak: dict[int, int] = {}

    # ------------------------------------------------------------------ state

    def services(self) -> list[LLMService]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, code, name, base_url, model, api_key_env, priority, paid, "
                    "requests_per_minute, requests_per_day, json_mode, input_usd_per_mtok, "
                    "output_usd_per_mtok, cooldown_until FROM llm_providers "
                    "WHERE enabled ORDER BY priority, id"
                )
            ).all()
        return [LLMService(**row._mapping) for row in rows]

    def _usage_today(self) -> dict[int, tuple[int, Decimal]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT provider_id, requests, cost_usd FROM llm_usage WHERE usage_date = :d"),
                {"d": taipei_today(self._clock())},
            ).all()
        return {r.provider_id: (int(r.requests), Decimal(r.cost_usd)) for r in rows}

    def daily_usd_cap(self) -> Decimal:
        with self.engine.connect() as conn:
            value = conn.execute(
                text("SELECT value -> 'llmDailyUsdCap' FROM settings WHERE key = 'news'")
            ).scalar_one_or_none()
        try:
            return Decimal(str(value)) if value is not None else Decimal(0)
        except ArithmeticError:
            return Decimal(0)

    def available(self) -> list[tuple[LLMService, str]]:
        """Services that may be asked right now, with their keys, in priority order."""
        now = self._clock()
        usage = self._usage_today()
        cap = self.daily_usd_cap()
        spent = sum((cost for _, cost in usage.values()), Decimal(0))
        out = []
        for service in self.services():
            key = (self.env.get(service.api_key_env) or "").strip()
            if not key:
                continue
            if service.cooldown_until is not None and service.cooldown_until > now:
                continue
            requests = usage.get(service.id, (0, Decimal(0)))[0]
            if service.requests_per_day is not None and requests >= service.requests_per_day:
                continue
            if service.paid and spent >= cap:
                continue
            out.append((service, key))
        return out

    # ------------------------------------------------------------------ requests

    def ask[M: BaseModel](self, system: str, user: str, model: type[M]) -> Answer[M]:
        """The first valid answer; NoLLMServiceError lists every failure when none answers."""
        failures: list[str] = []
        candidates = self.available()
        if not candidates:
            raise NoLLMServiceError("no LLM service available (keys, quotas or cooldowns)")
        schema = model.model_json_schema()
        for service, key in candidates:
            self._pace(service)
            try:
                completion = self.client.complete(service, key, system, user, schema)
            except LLMRateLimitedError as exc:
                rest = timedelta(seconds=exc.retry_after) if exc.retry_after else RATE_LIMIT_REST
                self._record(service, None, str(exc), rest=max(rest, timedelta(seconds=30)))
                failures.append(str(exc))
                continue
            except LLMUnavailableError as exc:
                self._record(service, None, str(exc), rest=UNAVAILABLE_REST)
                failures.append(str(exc))
                continue
            except LLMError as exc:
                self._record(service, None, str(exc))
                failures.append(str(exc))
                continue
            try:
                value = model.model_validate_json(extract_json(completion.text))
            except (LLMError, ValidationError, ValueError) as exc:
                message = f"invalid answer from {service.code}: {str(exc)[:300]}"
                self._record(service, completion, message)
                failures.append(message)
                continue
            self._record(service, completion, None)
            return Answer(value, service, completion)
        raise NoLLMServiceError("; ".join(failures))

    def _pace(self, service: LLMService) -> None:
        if not service.requests_per_minute:
            return
        interval = 60.0 / service.requests_per_minute
        last = self._last_call.get(service.id)
        if last is not None:
            wait = last + interval - self._monotonic()
            if wait > 0:
                self._sleep(wait)
        self._last_call[service.id] = self._monotonic()

    def _record(
        self,
        service: LLMService,
        completion: Completion | None,
        error: str | None,
        rest: timedelta | None = None,
    ) -> None:
        """Usage of one request, and the service's error state."""
        now = self._clock()
        tokens_in = completion.input_tokens if completion else 0
        tokens_out = completion.output_tokens if completion else 0
        if error is None:
            self._streak[service.id] = 0
        else:
            self._streak[service.id] = self._streak.get(service.id, 0) + 1
            if rest is None and self._streak[service.id] >= ERROR_STREAK:
                rest = ERROR_REST
            log.warning("LLM %s: %s", service.code, error)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO llm_usage (provider_id, usage_date, requests, failures, "
                    "input_tokens, output_tokens, cost_usd) VALUES (:id, :d, 1, :f, :i, :o, :c) "
                    "ON CONFLICT (provider_id, usage_date) DO UPDATE SET "
                    "requests = llm_usage.requests + 1, failures = llm_usage.failures + :f, "
                    "input_tokens = llm_usage.input_tokens + :i, "
                    "output_tokens = llm_usage.output_tokens + :o, "
                    "cost_usd = llm_usage.cost_usd + :c"
                ),
                {
                    "id": service.id,
                    "d": taipei_today(now),
                    "f": 0 if error is None else 1,
                    "i": tokens_in,
                    "o": tokens_out,
                    "c": service.cost(tokens_in, tokens_out),
                },
            )
            if error is None:
                conn.execute(
                    text("UPDATE llm_providers SET last_success_at = :now WHERE id = :id"),
                    {"now": now, "id": service.id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE llm_providers SET last_error = :e, last_error_at = :now, "
                        "cooldown_until = COALESCE(:until, cooldown_until) WHERE id = :id"
                    ),
                    {
                        "e": error[:1000],
                        "now": now,
                        "until": now + rest if rest else None,
                        "id": service.id,
                    },
                )


def check_service(
    service: LLMService, api_key: str, client: httpx.Client | None = None
) -> tuple[bool, str]:
    """Whether the service knows its model: GET {base_url}/models (all four services list
    their models there). Returns (ok, message) for /admin."""
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.get(
            service.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError as exc:
        return False, f"連線失敗：{exc}"
    if response.status_code in (401, 403):
        return False, f"金鑰被拒（HTTP {response.status_code}）"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    try:
        ids = {str(m.get("id", "")) for m in response.json().get("data", [])}
    except (ValueError, AttributeError):
        return False, "模型清單格式無法辨識"
    wanted = service.model
    if wanted in ids or f"models/{wanted}" in ids:
        return True, f"可用（{len(ids)} 個模型）"
    return False, f"找不到模型 {wanted}（共 {len(ids)} 個模型）"


def describe_schema(model: type[BaseModel]) -> str:
    """Compact JSON schema for prompts of services without json_schema support."""
    return json.dumps(model.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
