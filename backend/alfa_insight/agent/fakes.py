"""FakeLLM для черновика и доработки: InsightDraft по шаблону из промпта (без сети, детерминированно).

Черновик берёт числа и тексты только из evidence промпта, поэтому проходит проверки. Маркеры
`[[UNSUPPORTED]]` и др. из заголовков новостей переходят в факты — так тесты проверяют доработку и деградацию.
"""

from __future__ import annotations

import json
import re
from typing import Any

from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import LLMRequest

_HEAD = re.compile(r"^\[(?P<eid>E\d+)\] (?P<label>[^·\n]+?) · (?P<title>.+)$", re.M)
_PATH = re.compile(r"^(?P<pid>P\d+) \[(?P<eid>E\d+)\] (?P<rest>.+)$", re.M)
_FEATURE = re.compile(r"^(?P<key>[a-z_]+(?:\.[A-Za-z0-9_.]+)?) — ", re.M)
_PRODUCT = re.compile(r"^(?P<id>[a-z_]+) — .+Когда уместен", re.M)
_TAGS = re.compile(r"</?untrusted_document[^>]*>")


def _user(req: LLMRequest) -> str:
    return next((m.content for m in req.messages if m.role == "user" and isinstance(m.content, str)), "")


def _sentence(text: str, limit: int = 300) -> str:
    text = " ".join(_TAGS.sub(" ", text).split())
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    cut = cut[:limit].rstrip(" ,;:")
    return cut if cut.endswith((".", "!", "?")) else cut + "."


def _evidence(user: str) -> list[dict[str, str]]:
    heads = list(_HEAD.finditer(user))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else user.find("\nПути влияния", m.end())
        body = user[m.end() : end if end > 0 else None]
        title = m.group("title").split(" · ")[0]
        out.append(
            {"eid": m.group("eid"), "label": m.group("label").strip(), "title": title, "body": body.strip()}
        )
    return out


def fake_draft_from_prompt(user: str) -> dict[str, Any]:
    ev = _evidence(user)
    news = [e for e in ev if e["label"] in ("Новость", "Ваш текст")]
    alfa = [e for e in ev if e["label"] == "Аналитика Альфа-Банка"]
    profile = next((e for e in ev if e["title"] == "Профиль компании"), None)
    paths = [m.groupdict() for m in _PATH.finditer(user)]
    features = [
        m.group("key")
        for m in _FEATURE.finditer(user.split("Признаки (ключи для client_features_used):")[-1])
    ]
    products = [m.group("id") for m in _PRODUCT.finditer(user)]
    lead = news[0] if news else (ev[0] if ev else {"eid": "E1", "title": "Событие", "body": ""})
    facts = [{"text": _sentence(n["title"]), "type": "fact", "refs": [n["eid"]]} for n in news[:2]] or [
        {"text": _sentence(lead["title"]), "type": "fact", "refs": [lead["eid"]]}
    ]
    if paths:
        p1 = paths[0]
        parts = p1["rest"].split(" · ")
        link, risk = parts[3] if len(parts) > 3 else parts[-1], " · риск · " in p1["rest"]
        mechanism = parts[-1]
        summary = {"text": _sentence(f"Связь с компанией: {link}"), "type": "fact", "refs": [p1["eid"]]}
        direction = "risk" if risk else "opportunity"
    else:
        mechanism, direction = "влияние на компанию слабое", "mixed"
        ref = profile["eid"] if profile else lead["eid"]
        summary = {
            "text": "Связь события с компанией по данным слабая.",
            "type": "ai",
            "refs": [ref],
            "confidence": "low",
        }
    used = [k for k in features if k.startswith(("suppliers.", "buyers.", "factor.", "industry.main"))][
        :3
    ] or features[:1]
    kind = "risk" if direction != "opportunity" else "opportunity"
    consequence = {
        "kind": kind, "title": mechanism[:80] or "Влияние на компанию", "probability": "medium", "impact": "medium",
        "horizon": "weeks",
        "claim": {"text": _sentence(f"Возможное последствие: {mechanism}"), "type": "ai",
                  "refs": [paths[0]["eid"]] if paths else [lead["eid"]], "confidence": "medium"},
    }  # fmt: skip
    action = {
        "title": "Оценить влияние на бюджет и план закупок", "owner_role": "cfo", "urgency": "this_week",
        "product_id": products[0] if products else None,
        "claim": {"text": "Пересчитать бюджет с учётом события и обсудить с менеджером банка меры защиты.",
                  "type": "ai", "refs": [lead["eid"]], "confidence": "medium"},
    }  # fmt: skip
    bank = {"available": False, "claims": [], "alignment": "no_data"}
    if alfa:
        bank = {"available": True, "alignment": "neutral",
                "claims": [{"text": _sentence(alfa[0]["body"], 250), "type": "bank", "refs": [alfa[0]["eid"]]}]}  # fmt: skip
    title = lead["title"]
    return {
        "headline": (title[:70].rstrip() + ": что это значит для компании")[:110],
        "why_you": summary["text"][:140],
        "direction": direction,
        "impact_level": "medium",
        "what_happened": {"facts": facts, "assumptions": []},
        "why_it_matters": {
            "summary": summary,
            "client_features_used": used,
            "chain_ids": [p["pid"] for p in paths[:2]],
        },
        "consequences": [consequence],
        "actions": [action],
        "bank_view": bank,
    }


@fake_handler("draft")
def fake_draft(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any] | None:
    user = _user(req)
    if "Подготовь InsightDraft" not in user:
        return None  # чужой промпт (тесты роутера) — ответ по схеме запроса
    return fake_draft_from_prompt(user)


@fake_handler("revise")
def fake_revise(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Удаляет утверждения из замечаний (если блок не опустеет), убирает маркеры тестов."""
    last = next(
        (m.content for m in reversed(req.messages) if m.role == "user" and isinstance(m.content, str)), ""
    )
    if "Черновик:\n" not in last:
        return None
    draft = json.loads(last.split("Черновик:\n", 1)[1].rsplit("\n\nИсправь", 1)[0])
    bad = set(re.findall(r"^- ([^:\s]+):", last, re.M))
    wh = draft["what_happened"]
    keep = [f for i, f in enumerate(wh["facts"]) if f"what_happened.facts[{i}]" not in bad]
    wh["facts"] = keep or wh["facts"][:1]
    wh["assumptions"] = [
        a for i, a in enumerate(wh["assumptions"]) if f"what_happened.assumptions[{i}]" not in bad
    ]
    for _, c in _claims(draft):
        if "[[STICKY]]" not in c["text"]:
            c["text"] = re.sub(r"\s*\[\[[A-Z]+\]\]", "", c["text"])
    return draft


def _claims(d: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [(f"what_happened.facts[{i}]", c) for i, c in enumerate(d["what_happened"]["facts"])]
    out += [(f"what_happened.assumptions[{i}]", c) for i, c in enumerate(d["what_happened"]["assumptions"])]
    out.append(("why_it_matters.summary", d["why_it_matters"]["summary"]))
    out += [(f"consequences[{i}].claim", x["claim"]) for i, x in enumerate(d["consequences"])]
    out += [(f"actions[{i}].claim", x["claim"]) for i, x in enumerate(d["actions"])]
    out += [(f"bank_view.claims[{i}]", c) for i, c in enumerate(d["bank_view"]["claims"])]
    return out
