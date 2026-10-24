from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.schemas import InsightDraft
from alfa_insight.agent.verifier import VerifyInputs, degrade, deterministic_checks, verify
from alfa_insight.appctx import build_context
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.products.catalog import ProductCandidate
from alfa_insight.settings import Settings
from alfa_insight.store.runs import RunStore
from tests.unit.ranking.helpers import profile

CANDIDATES = [
    ProductCandidate(
        product_id="credit_line_working_capital",
        name="Кредитная линия",
        pitch="…",
        when="…",
        score=0.3,
        path_id="P1",
    )
]
INPUTS = VerifyInputs(
    feature_keys={"industry.main", "suppliers.metallurgy"}, path_ids=["P1", "P2"], exposure_direction="risk",
    expected_impact="medium", candidates=CANDIDATES,
)  # fmt: skip


def claim(
    text: str, type: str = "fact", refs: list[str] | None = None, confidence: str | None = None
) -> dict[str, Any]:
    return {
        "text": text,
        "type": type,
        "refs": refs if refs is not None else ["E1"],
        "confidence": confidence,
    }


def base_draft(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "headline": "Арматура дорожает: себестоимость объектов может вырасти",
        "why_you": "34% ваших закупок — металлургия",
        "direction": "risk",
        "impact_level": "high",
        "what_happened": {"facts": [claim("Металлурги поднимают цены на арматуру на 8% с ноября.")], "assumptions": []},
        "why_it_matters": {
            "summary": claim("Металлургия — 34% ваших закупок, рост цен увеличит затраты.", refs=["E2", "E1"]),
            "client_features_used": ["suppliers.metallurgy"],
            "chain_ids": ["P1"],
        },
        "consequences": [
            {"kind": "risk", "title": "Рост себестоимости", "probability": "high", "impact": "medium", "horizon": "weeks",
             "claim": claim("Себестоимость объектов вырастет из-за дорогого металла.", "ai", ["E2"], "medium")},
        ],
        "actions": [
            {"title": "Закупить металл заранее", "owner_role": "cfo", "urgency": "this_week",
             "product_id": "credit_line_working_capital",
             "claim": claim("Закупка до повышения цен зафиксирует текущую стоимость металла.", "ai", ["E1"], "high")},
        ],
        "bank_view": {"available": True, "alignment": "supports",
                      "claims": [claim("Аналитики банка ожидают роста цен на сталь на 5–7%.", "bank", ["E3"])]},
    }  # fmt: skip
    d.update(over)
    return d


@pytest.fixture
def actx(settings: Settings) -> AgentContext:
    app = build_context(settings)
    app.set_router(build_router(settings, app.db, backend=FakeBackend()))
    run_id = RunStore(app.db).create(kind="insight", mode="pipeline", company_id="SYN-DEMO-02")
    p = profile("SYN-DEMO-02", "construction_buildings", suppliers={"metallurgy": 0.34}, coverage=(0.9, 0.0))
    ctx = AgentContext.create(
        app, run_id=run_id, kind="insight", mode="pipeline", profile=p, role="cfo", event_id=None
    )
    reg = ctx.evidence
    reg.add(source_id="news:1", kind="news", title="Арматура дорожает", url="https://www.interfax.ru/business/1",
            text="Металлурги поднимают цены на арматуру на 8% с 1 ноября.", publisher="Интерфакс",
            published_at=datetime(2026, 10, 22, tzinfo=UTC))  # fmt: skip
    reg.add(source_id="data:SYN-DEMO-02:supply:metallurgy", kind="client_data", title="Закупки",
            text="Доля закупок у металлургии: 34%.")  # fmt: skip
    reg.add(source_id="alfa:metals:p3:c1", kind="alfa", title="Металлы, с. 3",
            text="Мы ожидаем роста цен на сталь на 5–7% в четвёртом квартале.")  # fmt: skip
    reg.add(
        source_id="cbr:key_rate:2026-10-22", kind="cbr", title="Ключевая ставка", text="Ключевая ставка: 14%."
    )
    return ctx


def checks(ctx: AgentContext, d: dict[str, Any], inp: VerifyInputs = INPUTS):  # type: ignore[no-untyped-def]
    fixed, results = deterministic_checks(InsightDraft.model_validate(d), ctx.evidence, inp)
    return fixed, {r.code: r for r in results}


def test_clean_draft(actx: AgentContext) -> None:
    _, r = checks(actx, base_draft())
    assert {c: x.status for c, x in r.items() if x.status != "pass"} == {}
    report = asyncio.run(verify(actx, InsightDraft.model_validate(base_draft()), INPUTS))[1]
    assert report.passed and report.supported_share == 1.0 and not report.llm_skipped and not report.issues
    assert len(report.verdicts) == len(InsightDraft.model_validate(base_draft()).claims())


def test_numbers_autofix_attaches_source(actx: AgentContext) -> None:
    """Число есть в другом evidence (ставка ЦБ) — ссылка добавляется, утверждение не удаляется."""
    d = base_draft()
    d["bank_view"]["claims"][0]["text"] = "Аналитики банка ожидают роста цен на сталь на 5–7% при ставке 14%."
    fixed, r = checks(actx, d)
    assert r["numbers_match"].status == "warn" and r["numbers_match"].paths == ["bank_view.claims[0]"]
    assert fixed.bank_view.claims[0].refs == ["E3", "E4"]
    assert r["bank_has_alfa"].status == "pass"

    # числа нет ни в одном evidence — fail, ссылки не трогаются
    d["bank_view"]["claims"][0]["text"] = "Аналитики банка ожидают роста цен на сталь на 5–7% при ставке 17%."
    fixed, r = checks(actx, d)
    assert r["numbers_match"].status == "fail" and fixed.bank_view.claims[0].refs == ["E3"]


def test_each_check(actx: AgentContext) -> None:
    d = base_draft()
    d["what_happened"]["facts"].append(
        claim("Минпромторг предложил новые меры поддержки отрасли.", refs=["E9"])
    )
    _, r = checks(actx, d)
    assert (
        r["refs_exist"].status == "fail"
        and r["refs_exist"].paths == ["what_happened.facts[1]"]
        and "E9" in r["refs_exist"].message
    )

    d = base_draft()
    d["what_happened"]["facts"][0]["text"] = "Металлурги поднимают цены на арматуру на 12% с ноября."
    _, r = checks(actx, d)
    assert r["numbers_match"].status == "fail" and "12%" in r["numbers_match"].message

    d = base_draft()
    d["consequences"][0]["claim"]["text"] = "Себестоимость может вырасти на 3,5% за квартал."
    _, r = checks(actx, d)
    assert r["numbers_match"].status == "warn"  # в выводе ИИ — только предупреждение

    d = base_draft()
    d["bank_view"]["claims"][0]["refs"] = ["E1"]
    _, r = checks(actx, d)
    assert r["bank_has_alfa"].status == "fail" and r["bank_has_alfa"].paths == ["bank_view.claims[0]"]

    d = base_draft()
    d["what_happened"]["facts"][0]["refs"] = ["E3"]  # факт только со ссылкой на аналитику
    _, r = checks(actx, d)
    assert r["fact_has_source"].status == "fail"

    d = base_draft()
    d["why_it_matters"]["client_features_used"] = ["suppliers.metallurgy", "made.up"]
    fixed, r = checks(actx, d)
    assert r["features_exist"].status == "warn" and fixed.why_it_matters.client_features_used == [
        "suppliers.metallurgy"
    ]
    d["why_it_matters"]["client_features_used"] = ["made.up"]
    _, r = checks(actx, d)
    assert r["features_exist"].status == "fail"

    d = base_draft()
    d["actions"][0]["claim"]["text"] = (
        "Подробнее об условиях — на сайте bestloans.com и в https://evil.example.ru/x."
    )
    _, r = checks(actx, d)
    assert r["no_foreign_urls"].status == "fail" and r["no_foreign_urls"].paths == ["actions[0].claim"]
    d["actions"][0]["claim"]["text"] = "Подробности в материале interfax.ru о ценах на металл."
    _, r = checks(actx, d)
    assert r["no_foreign_urls"].status == "pass"  # домен из evidence разрешён

    d = base_draft()
    d["actions"][0]["product_id"] = "crypto_wallet"
    fixed, r = checks(actx, d)
    assert r["products_valid"].status == "fail" and fixed.actions[0].product_id is None

    d = base_draft()
    d["actions"][0]["claim"]["text"] = "Это гарантированно убережёт компанию от потерь без риска."
    _, r = checks(actx, d)
    assert r["banned_phrases"].status == "warn" and "гарантированно" in r["banned_phrases"].message

    d = base_draft(impact_level="critical", direction="opportunity")
    d["consequences"][0]["claim"]["confidence"] = None
    d["why_it_matters"]["chain_ids"] = ["P1", "P7"]
    fixed, r = checks(actx, d)
    assert r["impact_consistent"].status == "warn" and fixed.impact_level == "high"
    assert r["direction_consistent"].status == "warn"
    assert r["ai_has_confidence"].status == "warn" and fixed.consequences[0].claim.confidence == "medium"
    assert r["chain_ids_exist"].status == "warn" and fixed.why_it_matters.chain_ids == ["P1"]

    d = base_draft()
    d["bank_view"] = {"available": True, "alignment": "supports", "claims": []}
    fixed, r = checks(actx, d)
    assert r["bank_view_consistency"].status == "warn"
    assert (fixed.bank_view.available, fixed.bank_view.alignment) == (False, "no_data")

    empty = InsightDraft.model_validate(base_draft()).model_copy(update={"consequences": [], "actions": []})
    _, results = deterministic_checks(empty, actx.evidence, INPUTS)
    comp = next(x for x in results if x.code == "completeness")
    assert comp.status == "fail" and "риски и возможности" in comp.message and "что делать" in comp.message


def test_pass_rule_and_issues(actx: AgentContext) -> None:
    d = base_draft()
    d["what_happened"]["facts"].append(
        claim("Спрос на арматуру снизится вдвое [[UNSUPPORTED]].", refs=["E1"])
    )
    d["what_happened"]["facts"].append(claim("Цены на прокат тоже растут [[PARTIAL]].", refs=["E1"]))
    _, rep = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    assert not rep.passed
    # fact×4 + bank×1: supported 3, partial 0.5, unsupported 0 → 3.5/5
    assert rep.supported_share == 0.7
    assert any(i.startswith("what_happened.facts[1]: в источниках этого нет") for i in rep.issues)
    assert any(i.startswith("what_happened.facts[2]: уточни") for i in rep.issues)

    d = base_draft()
    d["what_happened"]["facts"][0]["text"] = "Металлурги поднимают цены на арматуру на 12% [[CONTRADICTED]]."
    _, rep = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    assert not rep.passed and rep.issues[0].startswith("what_happened.facts[0]: Чисел нет")
    assert any("источники говорят обратное" in i for i in rep.issues)

    d = base_draft()
    d["consequences"][0]["claim"]["text"] = "Себестоимость объектов вырастет [[MISSING]]."
    _, rep = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    # все блоки на месте — «missing» судьи не блокирует, но попадает в замечания
    assert rep.passed and rep.missing and "Не хватает ответа: что делать" in rep.issues
    trace = [t.type for t in RunStore(actx.app.db).trace(actx.run_id)]
    assert "verify.report" in trace and "llm.call" not in trace  # слушатель трассы подключает runtime


def test_skip_if_clean(actx: AgentContext) -> None:
    actx.app.settings.verify_llm_skip_if_clean = True
    _, rep = asyncio.run(verify(actx, InsightDraft.model_validate(base_draft()), INPUTS))
    assert rep.llm_skipped and rep.passed and rep.verdicts == []


def test_degradation(actx: AgentContext) -> None:
    d = base_draft()
    d["what_happened"]["facts"].append(
        claim("Цена выросла на 40% за неделю.", refs=["E1"])
    )  # число не из источника
    d["consequences"].append(
        {"kind": "opportunity", "title": "Новые контракты", "probability": "low", "impact": "low", "horizon": "months",
         "claim": claim("Конкуренты уйдут с рынка [[UNSUPPORTED]].", "ai", ["E1"], "low")}
    )  # fmt: skip
    draft = InsightDraft.model_validate(d)
    fixed, rep = asyncio.run(verify(actx, draft, INPUTS))
    res = degrade(fixed, rep)
    assert (
        res.removed_claims == 2
        and len(res.draft.what_happened.facts) == 1
        and len(res.draft.consequences) == 1
    )
    assert res.status == "published" and res.supported_share == 1.0 and res.warnings

    # summary не подтверждён → тип ai/low и needs_review; пустой блок не остаётся пустым
    d = base_draft()
    d["why_it_matters"]["summary"]["text"] = "Металлургия — 34% ваших закупок [[UNSUPPORTED]]."
    d["actions"][0]["claim"]["text"] = "Закупить металл до 1 ноября [[CONTRADICTED]]."
    fixed, rep = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    res = degrade(fixed, rep)
    assert res.status == "needs_review"
    assert (
        res.draft.why_it_matters.summary.type == "ai" and res.draft.why_it_matters.summary.confidence == "low"
    )
    assert len(res.draft.actions) == 1 and res.draft.actions[0].claim.confidence == "low"
    assert any("почему важно" in w for w in res.warnings)

    # все факты и банк не подтверждены → доля 0 → needs_review, bank_view пуст
    d = base_draft()
    d["what_happened"]["facts"][0]["text"] = "Металлурги поднимают цены [[UNSUPPORTED]]."
    d["bank_view"]["claims"][0]["refs"] = ["E1"]
    fixed, rep = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    res = degrade(fixed, rep)
    assert res.status == "needs_review" and res.draft.bank_view.available is False
    assert res.draft.bank_view.alignment == "no_data"


def test_internal_ids_stripped(actx: AgentContext) -> None:
    d = base_draft()
    d["consequences"][0]["claim"]["text"] = (
        "Путь влияния P1 указывает на рост затрат, это видно в источниках E1 и E2."
    )
    fixed, r = checks(actx, d)
    assert r["internal_ids"].status == "warn" and r["internal_ids"].paths == ["consequences[0].claim"]
    assert (
        fixed.consequences[0].claim.text == "Путь влияния указывает на рост затрат, это видно в источниках."
    )


def test_should_revise_interactive_hides_single_claim(actx: AgentContext) -> None:
    from alfa_insight.agent.pipeline_mode import should_revise

    d = base_draft()
    d["what_happened"]["facts"].append(claim("Аналитики оценили рынок проката в целом.", refs=["E3"]))
    draft, report = asyncio.run(verify(actx, InsightDraft.model_validate(d), INPUTS))
    assert not report.passed
    actx.priority = "interactive"
    assert not should_revise(actx, draft, report, attempts=1)
    assert any(
        t.type == "verify.check" and "Доработка не нужна" in t.title
        for t in RunStore(actx.app.db).trace(actx.run_id)
    )
    actx.priority = "precompute"
    assert should_revise(actx, draft, report, attempts=1)
    assert not should_revise(actx, draft, report, attempts=2)  # попытки исчерпаны
