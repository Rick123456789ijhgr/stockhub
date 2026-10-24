"""One LLM call analyses a batch of items: summary, sentiment, event type, importance,
topics and the stocks truly concerned (PLAN.md section 5).

Items are batched (BATCH_SIZE per request) to stretch the free services' daily request
limits. Each item lists the candidate stocks the rule-based matcher found; the model may
only confirm candidates, so a stock it invents is dropped. Social posts get the slang
dictionary (slang_terms) in the system prompt. Small deviations in an answer (an unknown
event type, a too-long summary, importance as text) are repaired instead of failing the
whole batch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

BATCH_SIZE = 5
TEXT_CHARS = 1500
"""Text per item sent to the model (titles always go whole)."""
SUMMARY_CHARS = 120

EVENT_TYPES = (
    "earnings",
    "revenue",
    "guidance",
    "dividend",
    "capital",
    "order",
    "product",
    "expansion",
    "merger",
    "management",
    "legal",
    "analyst",
    "institutional",
    "macro",
    "market",
    "rumor",
    "other",
)
EVENT_LABELS = {
    "earnings": "財報、獲利",
    "revenue": "營收",
    "guidance": "財測、展望、法說",
    "dividend": "股利、除權息",
    "capital": "增資、減資、面額、庫藏股、可轉債",
    "order": "訂單、客戶",
    "product": "產品、技術",
    "expansion": "擴產、投資、資本支出",
    "merger": "併購、合作、轉投資",
    "management": "經營層、董事會、股東會",
    "legal": "訴訟、裁罰、事故、資安",
    "analyst": "法人評等、目標價",
    "institutional": "籌碼、三大法人、大戶",
    "macro": "總經、政策、國際",
    "market": "大盤、類股盤勢",
    "rumor": "傳聞、未證實消息",
    "other": "其他",
}

Channel = Literal["news", "announcement", "social"]


class StockTone(BaseModel):
    symbol: str
    sentiment: float = Field(ge=-1, le=1)

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol(cls, value: object) -> str:
        return str(value).strip().upper()

    @field_validator("sentiment", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        return max(-1.0, min(1.0, float(value)))  # type: ignore[arg-type]


class ItemAnalysis(BaseModel):
    id: str
    summary: str
    sentiment: float = Field(ge=-1, le=1)
    event_type: str
    importance: int = Field(ge=1, le=5)
    topics: list[str] = Field(default_factory=list)
    stocks: list[StockTone] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: object) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= SUMMARY_CHARS else text[: SUMMARY_CHARS - 1] + "…"

    @field_validator("sentiment", mode="before")
    @classmethod
    def _sentiment(cls, value: object) -> float:
        return max(-1.0, min(1.0, float(value)))  # type: ignore[arg-type]

    @field_validator("event_type", mode="before")
    @classmethod
    def _event(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in EVENT_TYPES else "other"

    @field_validator("importance", mode="before")
    @classmethod
    def _importance(cls, value: object) -> int:
        return max(1, min(5, round(float(value))))  # type: ignore[arg-type]

    @field_validator("topics", mode="before")
    @classmethod
    def _topics(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for topic in value:
            text = str(topic).strip()
            if text and len(text) <= 20 and text not in out:
                out.append(text)
        return out[:3]


class BatchAnalysis(BaseModel):
    items: list[ItemAnalysis]


@dataclass(frozen=True)
class PromptItem:
    id: str
    channel: Channel
    source: str
    title: str
    text: str
    candidates: list[tuple[str, str]]
    """(symbol, name) the matcher found; the model may only confirm these."""


def system_prompt(social: bool, slang: list[tuple[str, str]]) -> str:
    events = "、".join(f"{key}（{label}）" for key, label in EVENT_LABELS.items())
    lines = [
        "你是台股研究助理。使用者給你一批新聞、公司重大訊息或股票論壇貼文（JSON 陣列），"
        '請逐則分析，只輸出一個 JSON 物件：{"items": [...]}，每則一個物件，id 照抄輸入。',
        "每則欄位：",
        f"- summary：繁體中文摘要，{SUMMARY_CHARS // 2} 字以內，只寫事實與數字，"
        "不加評論、不給投資建議。",
        "- sentiment：對所涉公司股價的影響，-1（非常負面）到 1（非常正面），中性為 0。",
        f"- event_type：從這些代碼選一個：{events}。",
        "- importance：對投資人的重要度 1～5。5＝可能明顯影響股價（財報大幅變化、重大訂單、"
        "併購、停工、重大裁罰）；3＝一般公司消息；1＝與投資無關或例行公告（如公告期間、"
        "法說會時間）。",
        "- topics：最多 3 個相關的產業或題材名詞（例如 半導體、AI伺服器、航運），沒有就空陣列。",
        "- stocks：只能從該則的 candidates 中挑出內容真正談到的公司，並給各自的 sentiment；"
        "只是順帶一提或同名誤判就不要列；都不相關就空陣列。",
        "不要輸出 JSON 以外的文字。",
    ]
    if social:
        lines += [
            "這批是股票論壇貼文，代表作者個人觀點：sentiment 指作者對該股的看法（看多為正、"
            "看空為負），留意反串與反諷；importance 依內容的資訊量給分，純情緒發言給 1～2。",
        ]
        if slang:
            lines.append("台股與鄉民用語：")
            lines += [f"- {term}：{meaning}" for term, meaning in slang]
    return "\n".join(lines)


def user_prompt(items: list[PromptItem]) -> str:
    payload: list[dict[str, Any]] = [
        {
            "id": item.id,
            "type": {"news": "新聞", "announcement": "重大訊息", "social": "論壇貼文"}[
                item.channel
            ],
            "source": item.source,
            "title": item.title,
            "text": item.text[:TEXT_CHARS],
            "candidates": [{"symbol": s, "name": n} for s, n in item.candidates],
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False)


def accept(batch: BatchAnalysis, items: list[PromptItem]) -> dict[str, ItemAnalysis]:
    """Answers by item id, keeping only stocks among each item's candidates. Items the
    model skipped are missing (they stay pending for the next round)."""
    wanted = {item.id: {s for s, _ in item.candidates} for item in items}
    out: dict[str, ItemAnalysis] = {}
    for answer in batch.items:
        if answer.id not in wanted or answer.id in out:
            continue
        stocks = [s for s in answer.stocks if s.symbol in wanted[answer.id]]
        out[answer.id] = answer.model_copy(update={"stocks": stocks})
    return out
