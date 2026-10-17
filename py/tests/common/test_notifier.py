from __future__ import annotations

import io
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from stockhub.common.notifier import ConsoleNotifier, EmailNotifier, LineNotifier


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


def test_line_notifier_is_a_placeholder() -> None:
    with pytest.raises(NotImplementedError, match="M6"):
        LineNotifier().send("s", "b")
