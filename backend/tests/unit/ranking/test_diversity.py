from __future__ import annotations

import json

from alfa_insight.ranking.diversity import diversify, diversify_rows, main_path_key


def row(event_id: int, score: float, channel: str, ref: str) -> dict:  # type: ignore[type-arg]
    key = "factor_id" if channel == "factor" else "industry_id"
    return {
        "event_id": event_id,
        "score": score,
        "chain_json": json.dumps({"paths": [{"channel": channel, key: ref}]}),
    }


def test_repeated_main_path_is_pushed_down() -> None:
    rows = [
        row(1, 0.80, "factor", "key_rate"), row(2, 0.78, "factor", "key_rate"), row(3, 0.76, "factor", "key_rate"),
        row(4, 0.40, "supply", "metallurgy"), row(5, 0.35, "own", "construction_buildings"),
    ]  # fmt: skip
    order = [r["event_id"] for r in diversify_rows(rows)]
    assert order[:4] == [1, 2, 4, 5] and order[-1] == 3  # 0.78·0.55 = 0.43 > 0.40; 0.76·0.55² = 0.23
    assert main_path_key(rows[3]) == "supply:metallurgy" and main_path_key({"event_id": 9}) == "event:9"


def test_no_repeats_keeps_order_and_is_stable() -> None:
    items = [("a", 3.0), ("b", 2.0), ("c", 2.0), ("d", 1.0)]
    assert diversify(items, score=lambda x: x[1], key=lambda x: x[0]) == items
    assert diversify([], score=lambda x: 0.0, key=str) == []
