"""Streaming intraday quotes: one long-lived broker session, sampled every round (D-123).

`QuoteStreamSession` drives the configured stream sources (PROVIDERS_QUOTE_STREAM, first =
primary): connect with exponential backoff, re-subscribe after every reconnect, treat a
silent feed as lost, fall back to the next source and finally to polling, and only try
the primary again after a cooldown (no flapping). Messages are buffered as delivered;
the caller lands each batch in RawStore before parsing it (rule 5) and folds the updates
into `LatestQuotes`, which merges trades and bid/ask into one `Quote` per stock.

Everything here is synchronous: SDK callbacks only append to a locked buffer, and the
job's own loop does the rest once per round.
"""

from __future__ import annotations

import logging
import threading
import time as time_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Literal

from stockhub.common.timeutil import TAIPEI, utcnow
from stockhub.etl.providers.base import (
    Market,
    PermanentProviderError,
    Quote,
    QuoteStreamProvider,
    QuoteUpdate,
    StreamMessage,
)

if TYPE_CHECKING:
    from stockhub.common.settings import Settings

log = logging.getLogger(__name__)

CONTINUOUS_TRADING = (time(9, 0), time(13, 25))
"""Continuous session in Taipei; the call auctions around it print no trades, so a quiet
feed there is normal and not checked for staleness."""

Mode = Literal["streaming", "polling"]


@dataclass(frozen=True)
class StreamPolicy:
    reconnect_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 30.0
    fallback_cooldown: float = 300.0
    stale_after: float = 120.0

    @classmethod
    def from_settings(cls, settings: Settings) -> StreamPolicy:
        return cls(
            reconnect_attempts=settings.quote_stream_reconnect_attempts,
            max_delay=settings.quote_stream_reconnect_max_delay,
            fallback_cooldown=settings.quote_stream_fallback_cooldown,
            stale_after=settings.quote_stream_stale_after,
        )

    def delay(self, attempt: int) -> float:
        """Wait after failed attempt number `attempt` (1-based): 1, 2, 4, ... capped."""
        return float(min(self.max_delay, self.base_delay * 2 ** (attempt - 1)))


# ----------------------------------------------------------------------------- cache

_TRADE_FIELDS = ("price", "open", "high", "low", "prev_close", "volume")


class LatestQuotes:
    """Latest `Quote` per symbol, merged from stream updates and polled snapshots.

    A trade update fills only the fields it carries; a bid/ask update replaces bid and
    ask (None there means no order on that side). Updates older than what is held only
    fill fields still missing. A new trading day starts the symbol afresh.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._sources: dict[str, str] = {}
        self._dirty: set[str] = set()

    def get(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def apply(self, update: QuoteUpdate, source: str) -> None:
        trade_date = update.at.astimezone(TAIPEI).date()
        current = self._quotes.get(update.symbol)
        if current is not None and current.trade_date > trade_date:
            return
        if current is None or current.trade_date < trade_date:
            current = Quote(
                symbol=update.symbol,
                market=update.market,
                trade_date=trade_date,
                at=update.at,
                price=None,
                volume=0,
            )
        fields: dict[str, object] = {}
        newer = update.at >= current.at
        for name in _TRADE_FIELDS:
            value = getattr(update, name)
            if value is not None and (newer or getattr(current, name) in (None, 0)):
                fields[name] = value
        if update.kind == "bidask" and newer:
            fields["bid"], fields["ask"] = update.bid, update.ask
        if newer:
            fields["at"] = update.at
        if fields:
            self._store(current.model_copy(update=fields), source)

    def put(self, quote: Quote, source: str, *, dirty: bool = True) -> None:
        """A whole snapshot (e.g. polled): replaces what is held unless it is older.

        `dirty=False` means the caller already stored it, so it is not written again.
        """
        current = self._quotes.get(quote.symbol)
        if current is not None and (current.trade_date, current.at) > (quote.trade_date, quote.at):
            return
        if current is not None and current.trade_date == quote.trade_date:
            keep = {n: getattr(current, n) for n in _TRADE_FIELDS if getattr(quote, n) is None}
            quote = quote.model_copy(update=keep)
        self._store(quote, source, dirty=dirty)

    def entries(self) -> list[tuple[Quote, str]]:
        """Every held quote with the source of its last update."""
        return [(q, self._sources[s]) for s, q in sorted(self._quotes.items())]

    def take_dirty(self) -> dict[str, list[Quote]]:
        """Quotes changed since the last call, grouped by the source of their last update."""
        out: dict[str, list[Quote]] = {}
        for symbol in sorted(self._dirty):
            out.setdefault(self._sources[symbol], []).append(self._quotes[symbol])
        self._dirty.clear()
        return out

    def _store(self, quote: Quote, source: str, *, dirty: bool = True) -> None:
        self._quotes[quote.symbol] = quote
        self._sources[quote.symbol] = source
        if dirty:
            self._dirty.add(quote.symbol)
        else:  # already written by the caller
            self._dirty.discard(quote.symbol)


# ----------------------------------------------------------------------------- session


def in_continuous_trading(at: datetime) -> bool:
    local = at.astimezone(TAIPEI).time()
    return CONTINUOUS_TRADING[0] <= local < CONTINUOUS_TRADING[1]


class QuoteStreamSession:
    """Keeps one stream source subscribed to the wanted symbols, or reports `polling`."""

    def __init__(
        self,
        streams: Sequence[QuoteStreamProvider],
        policy: StreamPolicy | None = None,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self.streams = list(streams)
        self.policy = policy or StreamPolicy()
        self.now, self.sleep = now, sleep
        self._lock = threading.Lock()
        self._buffer: dict[str, list[StreamMessage]] = {}
        self._lost: str | None = None
        self._last_message_at: datetime | None = None
        self._active: int | None = None
        """Index into `streams` of the connected source; None = polling."""
        self._connected_at: datetime | None = None
        self._silent_retry = False
        """The current connection replaced one that went stale."""
        self._retry_primary_at: datetime | None = None
        self._wanted: dict[str, Market] = {}
        self._streamed: dict[str, Market] = {}
        self.started = False
        self.reconnects = 0
        self.fallbacks = 0

    # ------------------------------------------------------------------ state

    @property
    def mode(self) -> Mode:
        return "polling" if self._active is None else "streaming"

    @property
    def source(self) -> QuoteStreamProvider | None:
        return None if self._active is None else self.streams[self._active]

    @property
    def streamed(self) -> frozenset[str]:
        """Symbols the active source is subscribed to (the rest must be polled)."""
        return frozenset(self._streamed) if self._active is not None else frozenset()

    def provider(self, name: str) -> QuoteStreamProvider:
        return next(p for p in self.streams if p.name == name)

    # ------------------------------------------------------------------ driving

    def set_symbols(self, symbols: Sequence[tuple[str, Market]]) -> None:
        """Wanted symbols; when connected, subscribes the difference right away."""
        self._wanted = dict(symbols)
        source = self.source
        if source is None:
            return
        target = self._capped(source)
        added = [(s, m) for s, m in target.items() if s not in self._streamed]
        removed = [(s, m) for s, m in self._streamed.items() if s not in target]
        try:
            if removed:
                source.unsubscribe(removed)
            if added:
                source.subscribe(added)
        except Exception as exc:
            self._mark_lost(source.name, f"subscription change failed: {exc}")
            return
        self._streamed = target
        if added or removed:
            log.info(
                "quote stream %s: subscribed +%d -%d, %d symbols",
                source.name,
                len(added),
                len(removed),
                len(target),
            )

    def start(self) -> Mode:
        """Connect the first source that works, in order; none -> polling."""
        self.started = True
        self._connect_from(0)
        return self.mode

    def ensure(self) -> Mode:
        """Once per round: recover a lost or stale source, or retry the primary when due."""
        if not self.started:
            return self.start()
        index = self._active
        if index is not None:
            reason = self._take_lost() or self._stale_reason()
            if reason is not None:
                gave_up = self._silent_retry and reason.startswith("stale")
                self._drop(reason)
                if gave_up:
                    log.warning(
                        "quote stream %s stays silent; falling back", self.streams[index].name
                    )
                    self._connect_from(index + 1)
                else:
                    self.reconnects += 1
                    stale = reason.startswith("stale")
                    if self._open(index, self.policy.reconnect_attempts):
                        self._silent_retry = stale
                    else:
                        self._connect_from(index + 1)
                return self.mode
        if self._active != 0 and self.streams and self._retry_due():
            self._retry_primary()
        return self.mode

    def drain(self) -> dict[str, list[StreamMessage]]:
        """Messages buffered since the last drain, per source name."""
        with self._lock:
            out, self._buffer = self._buffer, {}
        return out

    def close(self) -> None:
        if self._active is not None:
            self._drop("session closed")

    # ------------------------------------------------------------------ internals

    def _capped(self, source: QuoteStreamProvider, *, warn: bool = False) -> dict[str, Market]:
        symbols = sorted(self._wanted)
        if warn and len(symbols) > source.max_subscriptions:
            log.warning(
                "quote stream %s takes at most %d symbols; polling the other %d",
                source.name,
                source.max_subscriptions,
                len(symbols) - source.max_subscriptions,
            )
        return {s: self._wanted[s] for s in symbols[: source.max_subscriptions]}

    def _connect_from(self, first: int) -> None:
        for index in range(first, len(self.streams)):
            if self._open(index, self.policy.reconnect_attempts):
                self._silent_retry = False
                break
        else:
            if self.streams:
                log.warning("quote streams unavailable; polling")
        if self._active != 0 and self.streams:
            self.fallbacks += 1
            self._retry_primary_at = self.now() + timedelta(seconds=self.policy.fallback_cooldown)

    def _retry_due(self) -> bool:
        return self._retry_primary_at is not None and self.now() >= self._retry_primary_at

    def _retry_primary(self) -> None:
        """One attempt only, so a still-broken primary does not stall the fallback; the
        fallback stays connected until the primary is up, so no round goes without data."""
        previous = self.source
        if self._open(0, 1):
            if previous is not None:
                self._safe_disconnect(previous)
            self._silent_retry = False
            self._retry_primary_at = None
            log.info("quote stream back on primary %s", self.streams[0].name)
            return
        self._retry_primary_at = self.now() + timedelta(seconds=self.policy.fallback_cooldown)

    def _open(self, index: int, attempts: int) -> bool:
        source = self.streams[index]
        name = source.name
        for attempt in range(1, attempts + 1):
            log.info("quote stream %s: connecting (attempt %d/%d)", name, attempt, attempts)
            with self._lock:
                self._lost = None
            try:
                source.connect(
                    lambda message: self._receive(name, message),
                    lambda reason: self._mark_lost(name, reason),
                )
                target = self._capped(source, warn=attempt == 1)
                if target:
                    source.subscribe(list(target.items()))
            except PermanentProviderError as exc:
                log.error("quote stream %s refused: %s", name, exc)
                self._safe_disconnect(source)
                return False
            except Exception as exc:
                log.warning("quote stream %s: attempt %d failed: %s", name, attempt, exc)
                self._safe_disconnect(source)
                if attempt < attempts:
                    self.sleep(self.policy.delay(attempt))
                continue
            self._active = index
            self._connected_at = self.now()
            self._streamed = target
            log.info("quote stream %s: connected, subscribed %d symbols", name, len(target))
            return True
        log.warning("quote stream %s: gave up after %d attempts", name, attempts)
        return False

    def _drop(self, reason: str) -> None:
        source = self.source
        if source is None:
            return
        log.warning("quote stream %s: dropped (%s)", source.name, reason)
        self._safe_disconnect(source)
        self._active = None
        self._connected_at = None
        self._streamed = {}

    @staticmethod
    def _safe_disconnect(source: QuoteStreamProvider) -> None:
        try:
            source.disconnect()
        except Exception as exc:
            log.warning("quote stream %s: disconnect failed: %s", source.name, exc)

    def _receive(self, name: str, message: StreamMessage) -> None:
        with self._lock:
            self._buffer.setdefault(name, []).append(message)
            self._last_message_at = message.received_at

    def _mark_lost(self, name: str, reason: str) -> None:
        source = self.source
        if source is None or source.name != name:
            return  # a late callback from a source already dropped
        with self._lock:
            self._lost = reason

    def _take_lost(self) -> str | None:
        with self._lock:
            reason, self._lost = self._lost, None
        source = self.source
        if reason is None and source is not None and not source.is_connected():
            reason = "connection closed"
        return reason

    def _stale_reason(self) -> str | None:
        now = self.now()
        if self._connected_at is None or not self._streamed or not in_continuous_trading(now):
            return None
        with self._lock:
            last = self._last_message_at
        since = self._connected_at if last is None or last < self._connected_at else last
        if last is not None and last >= self._connected_at:
            self._silent_retry = False
        quiet = (now - since).total_seconds()
        if quiet <= self.policy.stale_after:
            return None
        return f"stale: no message for {quiet:.0f} s"
