"""News text helpers, stock linking and event deduplication (pure functions, M6).

Providers use the text helpers to clean what sources publish; sync_news uses the rest to
link items to stocks (PLAN.md section 5: direct mentions, industry and theme relations) and
to fold repeated reports of one event into its first item (D-139).
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SNIPPET_CHARS = 500
"""news_items.snippet limit (CHECK in the schema)."""

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|yclid|mc_[a-z]+|igshid|ref|ref_src|from|ocid)$")
_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", re.IGNORECASE)
_SPACES = re.compile(r"[ \t　\xa0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def normalize_url(url: str) -> str:
    """Canonical form of an article URL: lower-case host, no tracking parameters, sorted
    query, no trailing slash. A fragment is kept only for single-page apps (#/...)."""
    parts = urlsplit(url.strip())
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)
    )
    path = parts.path.rstrip("/") or "/"
    fragment = parts.fragment if parts.fragment.startswith("/") else ""
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), fragment)
    )


def html_to_text(value: str | None) -> str:
    """Visible text of an HTML fragment: entities decoded, tags dropped, line breaks kept,
    runs of spaces and blank lines collapsed."""
    if not value:
        return ""
    text = _BREAK.sub("\n", value)
    text = html.unescape(_TAG.sub("", text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def clip(text: str | None, limit: int = SNIPPET_CHARS) -> str | None:
    """At most `limit` characters, ending with … when cut; None for empty text."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def one_line(text: str) -> str:
    """Collapse all whitespace (titles that arrive with line breaks)."""
    return " ".join(text.split())


# ----------------------------------------------------------------------------- stock links

_COMMON_WORD_NAMES = """
統一 中華 大成 全新 可成 創意 世界 精華 大同 聯合 數字 光明 卓越 國產 大地 綠電 再生 幸福
台南 中天 太子 三星 無敵 大華 好德 互動 樂意 安心 合一 新興 精湛 時報 大樹 必應 春雨 秋雨
花王 惠普 佳能 遠見 大江 長虹 全家 光環 典範 公準 優群 青雲 大中 益安 是方 信實 天宇 博大
正道 上品 建國 聯華 東華 宏遠 得力 首利 冠軍 厚生 金寶 精英 順德 精元 創見 全科 加高 天良
中台 天品 大田 北基 百和 全國 信義 大略 前鼎 力士 豪展
"""
AMBIGUOUS_NAMES = frozenset(_COMMON_WORD_NAMES.split())
"""Two-character stock names that are common words; matched only through a tag, a
bracketed code or an alias (two-character names are over half of all names)."""

_NAME_SUFFIX = re.compile(r"\*|-(KY|創|DR)$")
_BRACKETED_CODE = re.compile(r"[(（\[【〔]\s*(\d{4}[0-9A-Z]{0,2})\s*(?:\.TWO?)?\s*[)）\]】〕]")
_ASCII_WORD = re.compile(r"^[A-Za-z0-9 .&-]+$")

MatchKind = str
"""How a stock was found: tag (the source said so), code, alias, name or short_name."""
STRONG = frozenset({"tag", "code", "alias", "name"})
"""Matches trusted without the LLM's confirmation; short (two-character) names are not."""


def clean_name(name: str) -> str:
    """Exchange short name without markers: 國巨* -> 國巨, 世芯-KY -> 世芯, 鈺寶-創 -> 鈺寶."""
    return _NAME_SUFFIX.sub("", _NAME_SUFFIX.sub("", name.strip())).strip()


class StockMatcher:
    """Finds the stocks a text mentions: bracketed codes ((2330)、【6488】), official short
    names (longest first, so 台積電 wins over a shorter overlapping name) and aliases."""

    def __init__(self, stocks: dict[str, tuple[int, str]], aliases: dict[str, int]) -> None:
        """`stocks`: symbol -> (stock_id, name) of listed stocks; `aliases`: alias -> stock_id."""
        self.ids = {symbol: stock_id for symbol, (stock_id, _) in stocks.items()}
        names: dict[str, int | None] = {}
        for stock_id, name in stocks.values():
            term = clean_name(name)
            if len(term) < 2:
                continue
            # Two stocks with one short name (a stock and its preferred share) match neither.
            names[term] = None if term in names and names[term] != stock_id else stock_id
        self.terms: dict[str, tuple[int, MatchKind]] = {
            term: (stock_id, "name" if len(term) >= 3 else "short_name")
            for term, stock_id in names.items()
            if stock_id is not None and term not in AMBIGUOUS_NAMES
        }
        ascii_aliases: dict[str, int] = {}
        for alias, stock_id in aliases.items():
            if _ASCII_WORD.match(alias):
                ascii_aliases[alias.lower()] = stock_id
            else:
                self.terms[alias] = (stock_id, "alias")
        ordered = sorted(self.terms, key=len, reverse=True)
        self._names = re.compile("|".join(map(re.escape, ordered))) if ordered else None
        self._ascii = ascii_aliases
        self._ascii_re = (
            re.compile(
                r"(?<![A-Za-z0-9])("
                + "|".join(map(re.escape, sorted(ascii_aliases, key=len, reverse=True)))
                + r")(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            if ascii_aliases
            else None
        )

    def find(self, text: str, tagged: list[str] | None = None) -> dict[int, MatchKind]:
        """stock_id -> the strongest way it was found in `text` (and the source's tags)."""
        found: dict[int, MatchKind] = {}
        rank = ["tag", "code", "alias", "name", "short_name"]

        def add(stock_id: int, kind: MatchKind) -> None:
            if stock_id not in found or rank.index(kind) < rank.index(found[stock_id]):
                found[stock_id] = kind

        for symbol in tagged or []:
            if symbol in self.ids:
                add(self.ids[symbol], "tag")
        for code in _BRACKETED_CODE.findall(text):
            if code in self.ids:
                add(self.ids[code], "code")
        if self._names is not None:
            for match in self._names.finditer(text):
                stock_id, kind = self.terms[match.group(0)]
                add(stock_id, kind)
        if self._ascii_re is not None:
            for match in self._ascii_re.finditer(text):
                add(self._ascii[match.group(1).lower()], "alias")
        return found


# ----------------------------------------------------------------------------- deduplication

DUPLICATE_WINDOW_HOURS = 48
SIMILAR_WITH_STOCK = 0.5
"""Title similarity (bigram Jaccard) that makes two reports of a shared stock one event."""
SIMILAR_WITHOUT_STOCK = 0.7
"""Stricter when neither report names a stock (market commentary looks alike)."""

_TITLE_PREFIX = re.compile(r"^\s*([【\[〈《(（][^】\]〉》)）]{1,8}[】\]〉》)）]\s*)+")
_NOT_WORD = re.compile(r"[^0-9a-z㐀-鿿]+")


def title_shingles(title: str) -> frozenset[str]:
    """Character bigrams of a title without its 【公告】-style prefix and punctuation."""
    text = _NOT_WORD.sub("", _TITLE_PREFIX.sub("", title).lower())
    if len(text) < 2:
        return frozenset({text}) if text else frozenset()
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_duplicate(
    url: str,
    title: str,
    published_hours: float,
    stock_ids: frozenset[int],
    earlier: list[tuple[int, str, str, float, frozenset[int]]],
) -> int | None:
    """The first earlier report of the same event, or None.

    `earlier`: (item_id, url, title, published_hours, stock_ids) of representative items of
    the same channel (not themselves duplicates), times in hours on any common scale.
    Same URL, or a similar title within DUPLICATE_WINDOW_HOURS that shares a stock (or where
    neither names one, with a stricter threshold).
    """
    shingles = title_shingles(title)
    for item_id, other_url, other_title, other_hours, other_stocks in sorted(
        earlier, key=lambda e: (e[3], e[0])
    ):
        if abs(published_hours - other_hours) > DUPLICATE_WINDOW_HOURS:
            continue
        if other_url == url:
            return item_id
        if stock_ids & other_stocks:
            threshold = SIMILAR_WITH_STOCK
        elif not stock_ids and not other_stocks:
            threshold = SIMILAR_WITHOUT_STOCK
        else:
            continue
        if jaccard(shingles, title_shingles(other_title)) >= threshold:
            return item_id
    return None


# ----------------------------------------------------------------------------- related stocks

INDUSTRY_WEIGHT = 0.3
"""Link weight of a watched stock whose industry an item is about (PLAN.md section 5)."""
THEME_WEIGHT = 0.5
"""Link weight of a member of a theme an item is about (themes are curated, so closer)."""
_INDUSTRY_SUFFIX = re.compile(r"(工業|業)$")


def topic_matches(topic: str, name: str) -> bool:
    """LLM topic vs an industry or theme name: 半導體 ~ 半導體業, 鋼鐵 ~ 鋼鐵工業,
    AI伺服器 ~ ai伺服器."""
    a = _INDUSTRY_SUFFIX.sub("", topic.strip().lower())
    b = _INDUSTRY_SUFFIX.sub("", name.strip().lower())
    return bool(a) and a == b


def related_links(
    topics: list[str],
    direct: set[int],
    watched_industries: dict[int, str],
    theme_members: dict[str, list[int]],
) -> dict[int, tuple[str, float]]:
    """stock_id -> (relation, weight) for stocks related through the item's topics.

    Industry relations only reach watched stocks (holdings and watchlist), because an
    industry holds up to a few hundred stocks; theme relations reach every current member.
    Stocks the item names directly keep their direct link.
    """
    out: dict[int, tuple[str, float]] = {}
    for topic in topics:
        for name, members in theme_members.items():
            if topic_matches(topic, name):
                for stock_id in members:
                    if stock_id not in direct:
                        out[stock_id] = ("theme", THEME_WEIGHT)
        for stock_id, industry in watched_industries.items():
            if stock_id not in direct and stock_id not in out and topic_matches(topic, industry):
                out[stock_id] = ("industry", INDUSTRY_WEIGHT)
    return out
