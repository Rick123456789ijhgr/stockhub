"""Outbound notifications: console in dev, email via SMTP, LINE and Telegram (M6, D-141).

NOTIFIER lists the channels in order (e.g. line,telegram,email). With more than one, the
RoutingNotifier sends by severity: critical to every channel; warning to the first push
channel (LINE, then Telegram) that is ready, LINE counting as not ready when under 10% of
its monthly quota is left, falling back to email; info to email only.
"""

from __future__ import annotations

import logging
import smtplib
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from email.message import EmailMessage
from types import TracebackType
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, Self, TextIO

import httpx

if TYPE_CHECKING:
    from stockhub.common.settings import Settings

log = logging.getLogger(__name__)

Severity = Literal["info", "warning", "critical"]
PUSH_TEXT_CHARS = 3500
"""Push messages are cut here (LINE allows 5000 characters, Telegram 4096)."""


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
    channel: ClassVar[str] = "console"
    """Name recorded in alerts.channels."""

    @abstractmethod
    def send(self, subject: str, body: str, severity: Severity = "warning") -> None: ...

    def deliver(self, subject: str, body: str, severity: Severity = "warning") -> list[str]:
        """Send and return the channels that accepted the message (raises if none did)."""
        self.send(subject, body, severity)
        return [self.channel]


class ConsoleNotifier(Notifier):
    """Development notifier: prints to stderr (or any stream)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        out = self.stream or sys.stderr
        print(f"[notify:{severity}] {subject}\n{body}", file=out, flush=True)


class EmailNotifier(Notifier):
    """SMTP notifier. Port 465 without STARTTLS uses implicit TLS."""

    channel: ClassVar[str] = "email"

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


def _push_text(subject: str, body: str, severity: Severity) -> str:
    prefix = {"info": "", "warning": "⚠️ ", "critical": "🚨 "}[severity]
    message = f"{prefix}{subject}\n\n{body}".strip()
    return message if len(message) <= PUSH_TEXT_CHARS else message[: PUSH_TEXT_CHARS - 1] + "…"


class LineNotifier(Notifier):
    """LINE Messaging API push to one user (LINE Notify ended in 2025; D-141).

    Needs a LINE Official Account channel access token and the user's own userId. The
    free plan has a monthly message quota; `remaining_share` reads it (cached 10 minutes).
    """

    channel: ClassVar[str] = "line"
    API = "https://api.line.me/v2/bot"

    def __init__(
        self,
        token: str,
        user_id: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_id = user_id
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self.headers = {"Authorization": f"Bearer {token}"}
        self._clock = clock
        self._quota: tuple[float, float | None] | None = None

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        response = self.client.post(
            f"{self.API}/message/push",
            headers=self.headers,
            json={
                "to": self.user_id,
                "messages": [{"type": "text", "text": _push_text(subject, body, severity)}],
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"LINE push failed: HTTP {response.status_code} {response.text[:200]}"
            )

    def remaining_share(self) -> float | None:
        """Share of this month's quota left (0..1); None when unlimited or unknown."""
        now = self._clock()
        if self._quota is not None and now - self._quota[0] < 600:
            return self._quota[1]
        share: float | None = None
        try:
            quota = self.client.get(f"{self.API}/message/quota", headers=self.headers).json()
            used = self.client.get(
                f"{self.API}/message/quota/consumption", headers=self.headers
            ).json()
            if quota.get("type") == "limited" and quota.get("value"):
                share = max(0.0, 1 - float(used.get("totalUsage", 0)) / float(quota["value"]))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            log.warning("could not read the LINE message quota")
        self._quota = (now, share)
        return share


class TelegramNotifier(Notifier):
    """Telegram Bot API sendMessage to one chat (free, no monthly quota)."""

    channel: ClassVar[str] = "telegram"

    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        response = self.client.post(
            self.url,
            json={
                "chat_id": self.chat_id,
                "text": _push_text(subject, body, severity),
                "disable_web_page_preview": True,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram send failed: HTTP {response.status_code}")


LINE_RESERVE = 0.1
"""Below this share of the monthly LINE quota, warnings go to the next channel (D-141)."""
PUSH_CHANNELS = ("line", "telegram")


class RoutingNotifier(Notifier):
    """Several channels in the user's order, chosen by severity (see the module doc)."""

    channel: ClassVar[str] = "routing"

    def __init__(self, channels: Sequence[Notifier]) -> None:
        if not channels:
            raise ValueError("RoutingNotifier needs at least one channel")
        self.channels = list(channels)

    def _ready(self, notifier: Notifier) -> bool:
        if isinstance(notifier, LineNotifier):
            share = notifier.remaining_share()
            return share is None or share >= LINE_RESERVE
        return True

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        self.deliver(subject, body, severity)

    def deliver(self, subject: str, body: str, severity: Severity = "warning") -> list[str]:
        if severity == "critical":
            targets, first_only = self.channels, False
        elif severity == "warning":
            push = [c for c in self.channels if c.channel in PUSH_CHANNELS and self._ready(c)]
            rest = [c for c in self.channels if c.channel not in PUSH_CHANNELS]
            targets, first_only = push + rest, True
        else:
            targets = [c for c in self.channels if c.channel not in PUSH_CHANNELS]
            first_only = False
        accepted: list[str] = []
        errors: list[str] = []
        for notifier in targets:
            try:
                notifier.send(subject, body, severity)
            except Exception as exc:
                errors.append(f"{notifier.channel}: {exc}")
                log.warning("notification via %s failed: %s", notifier.channel, exc)
                continue
            accepted.append(notifier.channel)
            if first_only:
                break
        if targets and not accepted:
            raise RuntimeError("no channel accepted the notification: " + "; ".join(errors))
        return accepted


def _channel(name: str, settings: Settings) -> Notifier:
    if name == "email":
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
    if name == "line":
        if not (settings.line_channel_access_token and settings.line_user_id):
            raise ValueError("NOTIFIER=line requires LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID")
        return LineNotifier(
            settings.line_channel_access_token.get_secret_value(), settings.line_user_id
        )
    if name == "telegram":
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            raise ValueError("NOTIFIER=telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return TelegramNotifier(
            settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id
        )
    return ConsoleNotifier()


def build_notifier(settings: Settings) -> Notifier:
    channels = [_channel(name, settings) for name in settings.notifier]
    return channels[0] if len(channels) == 1 else RoutingNotifier(channels)
