"""Prompt and answer handling for the batched news analysis (etl/news_analysis.py)."""

from __future__ import annotations

import json

from stockhub.etl.news_analysis import (
    SUMMARY_CHARS,
    BatchAnalysis,
    PromptItem,
    accept,
    system_prompt,
    user_prompt,
)

ITEMS = [
    PromptItem("1", "news", "工商時報", "台積電法說", "內文" * 2000, [("2330", "台積電")]),
    PromptItem("2", "social", "PTT 股票板", "[標的] 2059川湖 多", "看多", [("2059", "川湖")]),
]


def test_prompts() -> None:
    news = system_prompt(False, [("丸子", "完了")])
    assert "candidates" in news
    assert "丸子" not in news  # the dictionary is for social posts only
    social = system_prompt(True, [("丸子", "完了")])
    assert "- 丸子：完了" in social
    assert "反串" in social
    payload = json.loads(user_prompt(ITEMS))
    assert payload[0]["type"] == "新聞"
    assert payload[1]["type"] == "論壇貼文"
    assert len(payload[0]["text"]) == 1500
    assert payload[0]["candidates"] == [{"symbol": "2330", "name": "台積電"}]


def test_answers_are_repaired_and_limited_to_candidates() -> None:
    batch = BatchAnalysis.model_validate_json(
        json.dumps(
            {
                "items": [
                    {
                        "id": 1,
                        "summary": "長" * 300,
                        "sentiment": "1.4",
                        "event_type": "Earnings",
                        "importance": "4.6",
                        "topics": ["半導體", "半導體", "", "x" * 30, "AI", "先進封裝"],
                        "stocks": [
                            {"symbol": "2330 ", "sentiment": 0.8},
                            {"symbol": "2454", "sentiment": 0.1},
                        ],
                    },
                    {
                        "id": "2",
                        "summary": "看多",
                        "sentiment": -0.2,
                        "event_type": "gossip",
                        "importance": 0,
                    },
                    {"id": "9", "summary": "?", "sentiment": 0, "event_type": "x", "importance": 1},
                ]
            }
        )
    )
    answers = accept(batch, ITEMS)
    assert set(answers) == {"1", "2"}
    first = answers["1"]
    assert len(first.summary) == SUMMARY_CHARS
    assert first.sentiment == 1.0
    assert first.event_type == "earnings"
    assert first.importance == 5
    assert first.topics == ["半導體", "AI", "先進封裝"]
    assert [s.symbol for s in first.stocks] == ["2330"]  # 2454 was not a candidate
    second = answers["2"]
    assert (second.event_type, second.importance, second.stocks) == ("other", 1, [])
