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
