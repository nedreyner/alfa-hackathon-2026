"""Реестр evidence прогона: E1, E2, … ↔ постоянные source_id (docs/08-agent.md §4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from alfa_insight.agent.schemas import SourceKind
from alfa_insight.text.numbers import extract_numbers

KIND_LABELS: dict[str, str] = {
    "news": "Новость",
    "alfa": "Аналитика Альфа-Банка",
    "cbr": "Данные ЦБ",
    "client_data": "Ваши данные",
    "user_input": "Ваш текст",
}
UNTRUSTED_KINDS = {"news", "alfa", "user_input"}


class EvidenceItem(BaseModel):
    eid: str
    source_id: str
    kind: SourceKind
    title: str
    publisher: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    text: str
    numbers: list[float]
    untrusted: bool
    meta: dict[str, Any] = Field(default_factory=dict)


class EvidenceRegistry:
    def __init__(self, *, text_chars: int = 1500, max_items: int = 30):
        self.text_chars = text_chars
        self.max_items = max_items
        self._items: list[EvidenceItem] = []
        self._by_source: dict[str, EvidenceItem] = {}

    def __len__(self) -> int:
        return len(self._items)

    @property
    def full(self) -> bool:
        return len(self._items) >= self.max_items

    def add(
        self,
        *,
        source_id: str,
        kind: SourceKind,
        title: str,
        text: str,
        publisher: str | None = None,
        url: str | None = None,
        published_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> EvidenceItem:
        existing = self._by_source.get(source_id)
        if existing is not None:
            return existing
        trimmed = text if len(text) <= self.text_chars else text[: self.text_chars].rstrip() + " […]"
        item = EvidenceItem(
            eid=f"E{len(self._items) + 1}",
            source_id=source_id,
            kind=kind,
            title=title,
            publisher=publisher,
            url=url,
            published_at=published_at,
            text=trimmed,
            numbers=[n.value for n in extract_numbers(trimmed)],
            untrusted=kind in UNTRUSTED_KINDS,
            meta=meta or {},
        )
        self._items.append(item)
        self._by_source[source_id] = item
        return item

    def get(self, eid: str) -> EvidenceItem | None:
        idx = int(eid[1:]) - 1 if eid.startswith("E") and eid[1:].isdigit() else -1
        return self._items[idx] if 0 <= idx < len(self._items) else None

    def by_source(self, source_id: str) -> EvidenceItem | None:
        return self._by_source.get(source_id)

    def all(self) -> list[EvidenceItem]:
        return list(self._items)

    @staticmethod
    def kind_label(item: EvidenceItem) -> str:
        return KIND_LABELS.get(item.kind, item.kind)
