from __future__ import annotations

import io
import json
from email.message import EmailMessage
from typing import Any, ClassVar

import httpx
import pytest

from stockhub.common.notifier import (
    ConsoleNotifier,
    EmailNotifier,
    LineNotifier,
    Notifier,
    RoutingNotifier,
    Severity,
    TelegramNotifier,
    build_notifier,
)


def test_console_notifier_writes_subject_and_body() -> None:
    out = io.StringIO()
    ConsoleNotifier(out).send("prices stale", "latest 2026-10-15", severity="critical")
    assert out.getvalue() == "[notify:critical] prices stale\nlatest 2026-10-15\n"


class _FakeSMTP:
    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.calls.append("quit")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


def test_email_notifier_sends_via_smtp() -> None:
    _FakeSMTP.instances.clear()
    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        sender="bot@example.com",
        recipients=["me@example.com", "you@example.com"],
        username="bot",
        password="pw",
        smtp_factory=_FakeSMTP,
    )
    notifier.send("價格資料落後", "最新 2026-10-15")

    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", "login:bot", "quit"]
    msg = smtp.sent[0]
    assert msg["Subject"] == "[StockHub] [警告] 價格資料落後"
    assert msg["To"] == "me@example.com, you@example.com"
    assert "最新 2026-10-15" in msg.get_content()


def test_email_notifier_without_credentials_skips_login() -> None:
    _FakeSMTP.instances.clear()
    EmailNotifier("h", 25, "a@b", ["c@d"], starttls=False, smtp_factory=_FakeSMTP).send("s", "b")
    assert _FakeSMTP.instances[0].calls == ["quit"]


def test_email_notifier_requires_recipients() -> None:
    with pytest.raises(ValueError, match="recipient"):
        EmailNotifier("h", 25, "a@b", [])


def _http(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_line_push_and_quota() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/quota"):
            return httpx.Response(200, json={"type": "limited", "value": 200})
        if request.url.path.endswith("/consumption"):
            return httpx.Response(200, json={"totalUsage": 185})
        return httpx.Response(200, json={})

    line = LineNotifier("tok", "U123", _http(handler), clock=lambda: 0.0)
    line.send("持股警示", "內容", "warning")
    push = seen[0]
    assert str(push.url) == "https://api.line.me/v2/bot/message/push"
    assert push.headers["authorization"] == "Bearer tok"
    body = json.loads(push.content)
    assert body["to"] == "U123"
    assert body["messages"] == [{"type": "text", "text": "⚠️ 持股警示\n\n內容"}]
    assert line.remaining_share() == pytest.approx(0.075)
    assert len(seen) == 3
    line.remaining_share()  # cached
    assert len(seen) == 3
    failing = LineNotifier("tok", "U1", _http(lambda _: httpx.Response(401, text="bad")))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        failing.send("s", "b")


def test_telegram_send_cuts_long_text() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    TelegramNotifier("123:abc", "42", _http(handler)).send("s", "長" * 5000, "info")
    assert str(seen[0].url) == "https://api.telegram.org/bot123:abc/sendMessage"
    body = json.loads(seen[0].content)
    assert body["chat_id"] == "42"
    assert len(body["text"]) == 3500
    assert body["text"].endswith("…")


class _Recorder(Notifier):
    def __init__(self, channel: str, fail: bool = False) -> None:
        self.channel = channel  # type: ignore[misc]
        self.fail, self.sent = fail, []  # type: ignore[var-annotated]

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        if self.fail:
            raise RuntimeError(f"{self.channel} down")
        self.sent.append((subject, severity))


class _QuotaLine(LineNotifier):
    def __init__(self, share: float | None, fail: bool = False) -> None:
        self.share, self.fail, self.sent = share, fail, []  # type: ignore[var-annotated]

    def remaining_share(self) -> float | None:
        return self.share

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        if self.fail:
            raise RuntimeError("line down")
        self.sent.append(subject)


def test_routing_by_severity_and_line_quota() -> None:
    line, telegram, email = _QuotaLine(0.5), _Recorder("telegram"), _Recorder("email")
    router = RoutingNotifier([line, telegram, email])
    assert router.deliver("a", "b", "critical") == ["line", "telegram", "email"]
    assert router.deliver("a", "b", "warning") == ["line"]
    assert router.deliver("a", "b", "info") == ["email"]
    # Under 10% of the LINE quota left: warnings go to Telegram, critical still to all.
    low = RoutingNotifier([_QuotaLine(0.05), telegram, email])
    assert low.deliver("a", "b", "warning") == ["telegram"]
    assert low.deliver("a", "b", "critical") == ["line", "telegram", "email"]
    # A failing channel falls through to the next one.
    broken = RoutingNotifier([_QuotaLine(None, fail=True), _Recorder("email")])
    assert broken.deliver("a", "b", "warning") == ["email"]
    with pytest.raises(RuntimeError, match="no channel accepted"):
        RoutingNotifier([_Recorder("email", fail=True)]).deliver("a", "b", "info")
    # Push-only setups have nothing for info messages.
    assert RoutingNotifier([_QuotaLine(0.5)]).deliver("a", "b", "info") == []


def test_build_notifier_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    from stockhub.common.settings import load_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("NOTIFIER", "line,telegram")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "t")
    monkeypatch.setenv("LINE_USER_ID", "U1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "b")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    notifier = build_notifier(load_settings())
    assert isinstance(notifier, RoutingNotifier)
    assert [c.channel for c in notifier.channels] == ["line", "telegram"]
    monkeypatch.setenv("NOTIFIER", "console")
    assert isinstance(build_notifier(load_settings()), ConsoleNotifier)
