from __future__ import annotations

import json
import os
from pathlib import Path

from alfa_insight.agent.schemas import Insight, InsightDraft, VerificationReport, VerifyLLMOutput
from alfa_insight.llm.fake import example_from_schema
from alfa_insight.llm.structured import schema_to_prompt, to_llm_schema

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent"
SNAPSHOT = FIXTURES / "insight_draft.schema.json"


def test_insight_draft_schema_snapshot() -> None:
    schema = to_llm_schema(InsightDraft)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert schema == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text and '"title": "' not in text.replace('"title": {', "")
    assert schema["required"] == [
        "headline", "why_you", "direction", "impact_level", "what_happened",
        "why_it_matters", "consequences", "actions", "bank_view",
    ]  # fmt: skip
    prompt = schema_to_prompt(schema)
    assert 'type: "fact" | "bank" | "ai";' in prompt and len(prompt) < 6000


def test_fake_example_validates() -> None:
    draft = InsightDraft.model_validate(example_from_schema(to_llm_schema(InsightDraft)))
    assert draft.consequences and draft.actions
    VerifyLLMOutput.model_validate(example_from_schema(to_llm_schema(VerifyLLMOutput)))


def test_full_insight_example() -> None:
    raw = json.loads((FIXTURES / "insight_example.json").read_text(encoding="utf-8"))
    ins = Insight.model_validate(raw)
    assert ins.why_you == "34% ваших закупок — металлургия" and ins.event.id == 123
    paths = [p for p, _ in ins.claims()]
    assert paths[:3] == ["what_happened.facts[0]", "what_happened.facts[1]", "what_happened.assumptions[0]"]
    assert "actions[1].claim" in paths and paths[-1] == "bank_view.claims[0]"
    refs = {r for _, c in ins.claims() for r in c.refs}
    assert refs <= {s.id for s in ins.sources}
    assert ins.products[0].action_index == 1 and ins.actions[1].product_id == ins.products[0].product_id
    # черновик — подмножество инсайта: те же блоки проходят валидацию InsightDraft
    InsightDraft.model_validate(ins.model_dump(include=set(InsightDraft.model_fields)))
    # круговой проход через JSON (так инсайт лежит в insights.payload_json)
    assert Insight.model_validate_json(ins.model_dump_json()) == ins


def test_verification_report_roundtrip() -> None:
    rep = VerificationReport(
        passed=False, attempt=1, checks=[], verdicts=[], contradictions=[], missing=[],
        supported_share=0.5, issues=["Утверждение без источника: actions[0].claim"], llm_skipped=True,
    )  # fmt: skip
    assert VerificationReport.model_validate_json(rep.model_dump_json()) == rep
