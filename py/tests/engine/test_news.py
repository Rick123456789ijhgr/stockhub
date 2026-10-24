"""News text cleanup, stock matching and event deduplication (engine/news.py)."""

from __future__ import annotations

from stockhub.engine.news import (
    StockMatcher,
    clean_name,
    clip,
    find_duplicate,
    html_to_text,
    jaccard,
    normalize_url,
    title_shingles,
)

STOCKS = {
    "2330": (1, "台積電"),
    "2454": (2, "聯發科"),
    "2316": (3, "楠梓電"),
    "2059": (4, "川湖"),
    "1216": (5, "統一"),
    "2327": (6, "國巨*"),
    "3661": (7, "世芯-KY"),
    "6488": (8, "環球晶"),
    "2881": (9, "富邦金"),
    "2881A": (10, "富邦特"),
    "1101": (11, "台泥"),
    "1101B": (12, "台泥"),  # a preferred share shares the short name
}
ALIASES = {"護國神山": 1, "台GG": 1, "TSMC": 1, "MTK": 2}


def test_normalize_url() -> None:
    assert (
        normalize_url("HTTPS://News.Example.com/a/b/?utm_source=x&id=2&fbclid=y&a=1#top")
        == "https://news.example.com/a/b?a=1&id=2"
    )
    assert normalize_url("https://mops.twse.com.tw/mops/#/web/t05st01?companyId=2330").endswith(
        "#/web/t05st01?companyId=2330"
    )
    assert normalize_url("https://a.example/") == "https://a.example/"


def test_html_to_text_and_clip() -> None:
    assert (
        html_to_text("<p>第一段&amp;更多</p><p>第二段<br>換行</p>") == "第一段&更多\n第二段\n換行"
    )
    assert html_to_text("  多   空　格  ") == "多 空 格"
    assert html_to_text(None) == ""
    assert clip("短") == "短"
    assert clip("一二三四五", 4) == "一二三…"
    assert clip("   ") is None


def test_clean_name() -> None:
    assert clean_name("國巨*") == "國巨"
    assert clean_name("世芯-KY") == "世芯"
    assert clean_name("矽力*-KY") == "矽力"
    assert clean_name("鈺寶-創") == "鈺寶"


def test_matcher_finds_names_codes_aliases_and_tags() -> None:
    matcher = StockMatcher(STOCKS, ALIASES)
    found = matcher.find("護國神山台積電(2330)帶動，聯發科與 tsmc ADR 同步走高")
    assert found == {1: "code", 2: "name"}
    assert matcher.find("TSMC 法說", tagged=["6488"]) == {1: "alias", 8: "tag"}
    # Two-character names count as short_name; common words are ignored entirely.
    assert matcher.find("[標的] 2059川湖 操作空間?") == {4: "short_name"}
    assert matcher.find("統一發票中獎號碼") == {}
    assert matcher.find("（1216）統一超") == {5: "code"}
    # Markers are stripped; the longest name wins over a contained shorter one.
    assert matcher.find("國巨與世芯走強，富邦金宣布配息") == {
        6: "short_name",
        7: "short_name",
        9: "name",
    }
    # A short name shared by two stocks matches neither; their codes still do.
    assert matcher.find("台泥（1101B）") == {12: "code"}
    # Codes are only trusted in brackets: years and prices are not stocks.
    assert matcher.find("2330元的目標價，2026年展望") == {}
    assert matcher.find("環球晶【6488.TWO】") == {8: "code"}
    assert matcher.find("台GG又噴了") == {1: "alias"}
    assert matcher.find("小MTKs") == {}


def test_title_similarity() -> None:
    assert title_shingles("【公告】台積電") == frozenset({"台積", "積電"})
    assert title_shingles("A") == frozenset({"a"})
    assert title_shingles("！") == frozenset()
    a = title_shingles("台積電法說會前夕 外資連三買")
    b = title_shingles("外資連三買台積電 法說會前夕卡位")
    assert jaccard(a, b) >= 0.5
    assert jaccard(a, title_shingles("聯發科新品發表")) < 0.1
    assert jaccard(frozenset(), a) == 0.0


def test_find_duplicate() -> None:
    earlier = [
        (10, "https://a/1", "台積電法說會前夕 外資連三買", 0.0, frozenset({1})),
        (11, "https://a/2", "聯發科新品發表", 1.0, frozenset({2})),
        (12, "https://a/3", "台股今日盤勢 加權指數收高", 2.0, frozenset()),
    ]
    assert (
        find_duplicate("https://b/1", "外資連三買台積電 法說會前夕卡位", 5, frozenset({1}), earlier)
        == 10
    )
    # Same URL is the same item whatever the title.
    assert find_duplicate("https://a/2", "別的標題", 3, frozenset(), earlier) == 11
    # Similar title but no shared stock: not merged.
    assert (
        find_duplicate("https://b/2", "外資連三買台積電 法說會前夕卡位", 5, frozenset({2}), earlier)
        is None
    )
    # Without stocks the threshold is stricter.
    assert find_duplicate("https://b/3", "台股今日盤勢 加權指數收高", 3, frozenset(), earlier) == 12
    assert find_duplicate("https://b/4", "台股今日盤勢偏弱", 3, frozenset(), earlier) is None
    # Outside the 48-hour window: a new event.
    assert (
        find_duplicate("https://b/5", "外資連三買台積電 法說會前夕", 60, frozenset({1}), earlier)
        is None
    )


def test_related_links() -> None:
    from stockhub.engine.news import related_links, topic_matches

    assert topic_matches("半導體", "半導體業")
    assert topic_matches("鋼鐵", "鋼鐵工業")
    assert topic_matches("AI伺服器", "ai伺服器")
    assert not topic_matches("半導體設備", "半導體業")
    assert not topic_matches("業", "業")
    links = related_links(
        ["半導體", "AI伺服器"],
        direct={1},
        watched_industries={1: "半導體業", 2: "半導體業", 3: "航運業"},
        theme_members={"AI伺服器": [1, 2, 4], "重電": [5]},
    )
    assert links == {2: ("theme", 0.5), 4: ("theme", 0.5)}
    assert related_links(["航運"], set(), {3: "航運業"}, {}) == {3: ("industry", 0.3)}
