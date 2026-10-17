"""Outbound notifications for ETL alerts (console in dev, email via SMTP; LINE in M6)."""

from __future__ import annotations

import smtplib
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from email.message import EmailMessage
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Protocol, Self, TextIO

if TYPE_CHECKING:
    from stockhub.common.settings import Settings

Severity = Literal["info", "warning", "critical"]


class SMTPClient(Protocol):
    """The subset of smtplib.SMTP used here (lets tests inject a fake)."""

    def __enter__(self) -> Self: ...
    def __exit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> object: ...
    def starttls(self) -> object: ...
    def login(self, user: str, password: str) -> object: ...
    def send_message(self, msg: EmailMessage) -> object: ...


class Notifier(ABC):
    @abstractmethod
    def send(self, subject: str, body: str, severity: Severity = "warning") -> None: ...


class ConsoleNotifier(Notifier):
    """Development notifier: prints to stderr (or any stream)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        out = self.stream or sys.stderr
        print(f"[notify:{severity}] {subject}\n{body}", file=out, flush=True)


class EmailNotifier(Notifier):
    """SMTP notifier. Port 465 without STARTTLS uses implicit TLS."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipients: Sequence[str],
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        timeout: float = 30.0,
        smtp_factory: Callable[..., SMTPClient] | None = None,
    ) -> None:
        if not recipients:
            raise ValueError("EmailNotifier needs at least one recipient")
        self.host, self.port, self.sender = host, port, sender
        self.recipients = list(recipients)
        self.username, self.password = username, password
        self.starttls, self.timeout = starttls, timeout
        implicit_tls = port == 465 and not starttls
        default: Callable[..., SMTPClient] = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        self._factory = smtp_factory or default

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        msg = EmailMessage()
        prefix = {"info": "", "warning": "[警告] ", "critical": "[嚴重] "}[severity]
        msg["Subject"] = f"[StockHub] {prefix}{subject}"
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(body)
        with self._factory(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username and self.password:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


class LineNotifier(Notifier):
    """Placeholder: LINE Messaging API integration arrives in M6."""

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        raise NotImplementedError("LINE notifications are implemented in milestone M6")


def build_notifier(settings: Settings) -> Notifier:
    if settings.notifier == "email":
        if not (settings.smtp_host and settings.smtp_from):
            raise ValueError("NOTIFIER=email requires SMTP_HOST and SMTP_FROM")
        return EmailNotifier(
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=settings.smtp_from,
            recipients=settings.alert_email_to,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            starttls=settings.smtp_starttls,
        )
    return ConsoleNotifier()
