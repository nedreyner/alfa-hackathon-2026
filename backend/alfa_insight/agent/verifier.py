"""Проверка черновика: детерминированные проверки, LLM-судья, правило прохождения, деградация (docs/08-agent.md §9)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.evidence import EvidenceItem, EvidenceRegistry
from alfa_insight.agent.schemas import (
    CheckResult,
    Claim,
    ClaimVerdict,
    InsightDraft,
    InsightStatus,
    VerificationReport,
    VerifyLLMOutput,
)
from alfa_insight.errors import LLMError
from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import LLMRequest
from alfa_insight.log import get_logger
from alfa_insight.products.catalog import ProductCandidate
from alfa_insight.ranking.models import ImpactLevel
from alfa_insight.text.numbers import extract_numbers, number_supported

log = get_logger("agent.verifier")

FACT_SOURCE_KINDS = {"news", "cbr", "client_data", "user_input"}
IMPACT_ORDER: list[ImpactLevel] = ["low", "medium", "high", "critical"]
PASS_SUPPORTED_SHARE = 0.8
PUBLISH_SUPPORTED_SHARE = 0.6
SKIP_IF_CLEAN_MAX_CLAIMS = 6
VERIFY_EVIDENCE_CHARS = 2000
VERDICT_SCORE = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0, "contradicted": 0.0}
# проверки, при fail которых утверждение удаляется при деградации (§9.5)
REMOVING_CHECKS = ("refs_exist", "fact_has_source", "bank_has_alfa", "numbers_match", "no_foreign_urls")

_URL = re.compile(
    r"(?:https?://|www\.)[^\s)»\"']+|\b(?:[a-z0-9-]+\.)+(?:ru|com|рф|org|net|io|su|info|biz)\b", re.I
)
_BANNED = [
    (re.compile(r"гарантированн", re.I), "«гарантированно»"),
    (re.compile(r"без\s+(?:всякого\s+)?риска", re.I), "«без риска»"),
    (re.compile(r"(?<![\d.,])100\s?%"), "«100%»"),
    (re.compile(r"(?:купите|покупайте|продайте|продавайте|приобретите)\s+(?:\w+\s+){0,2}(?:акци|облигаци|ценн\w+\s+бумаг)", re.I),
     "призыв купить или продать ценные бумаги"),
]  # fmt: skip


def _domain(url: str) -> str:
    host = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).split("/")[0]
    return host.split(":")[0]


@dataclass
class _Checks:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, code: str, status: str, message: str, paths: list[str] | None = None) -> None:
        self.results.append(CheckResult(code=code, status=status, message=message, paths=paths or []))  # type: ignore[arg-type]

    def failed_paths(self, codes: tuple[str, ...] | None = None) -> set[str]:
        return {
            p
            for r in self.results
            if r.status == "fail" and (codes is None or r.code in codes)
            for p in r.paths
        }


@dataclass
class VerifyInputs:
    """Что проверка знает помимо черновика."""

    feature_keys: set[str]
    path_ids: list[str]
    exposure_direction: str | None
    expected_impact: ImpactLevel | None
    candidates: list[ProductCandidate]


def inputs_from_context(
    ctx: AgentContext, candidates: list[ProductCandidate], expected_impact: ImpactLevel | None
) -> VerifyInputs:
    exp = ctx.exposure
    return VerifyInputs(
        feature_keys=ctx.profile.feature_keys(),
        path_ids=[p.id for p in exp.paths] if exp else [],
        exposure_direction=exp.direction if exp and exp.paths else None,
        expected_impact=expected_impact,
        candidates=candidates,
    )


def _cited(reg: EvidenceRegistry, claim: Claim) -> list[EvidenceItem]:
    return [e for e in (reg.get(r) for r in claim.refs) if e is not None]


def deterministic_checks(
    draft: InsightDraft, reg: EvidenceRegistry, inp: VerifyInputs
) -> tuple[InsightDraft, list[CheckResult]]:
    """§9.1. Возвращает исправленную копию черновика (автоисправления) и результаты проверок."""
    d = draft.model_copy(deep=True)
    ch = _Checks()
    claims = d.claims()

    # refs_exist
    bad = [p for p, c in claims if any(reg.get(r) is None for r in c.refs)]
    unknown = sorted({r for _, c in claims for r in c.refs if reg.get(r) is None})
    ch.add("refs_exist", "fail" if bad else "pass",
           f"Ссылки на несуществующие источники: {', '.join(unknown)}" if bad else "Все ссылки на источники существуют", bad)  # fmt: skip

    # fact_has_source / bank_has_alfa
    bad = [
        p
        for p, c in claims
        if c.type == "fact" and not any(e.kind in FACT_SOURCE_KINDS for e in _cited(reg, c))
    ]
    ch.add("fact_has_source", "fail" if bad else "pass",
           "Факт без источника: новости, данных ЦБ или данных клиента" if bad else "У фактов есть источники", bad)  # fmt: skip
    bad = [p for p, c in claims if c.type == "bank" and not any(e.kind == "alfa" for e in _cited(reg, c))]
    ch.add("bank_has_alfa", "fail" if bad else "pass",
           "Позиция банка без ссылки на аналитику Альфа-Банка" if bad else "Позиции банка подтверждены аналитикой", bad)  # fmt: skip

    # ai_has_confidence (автоисправление)
    fixed = [p for p, c in claims if c.type == "ai" and c.confidence is None]
    for _p, c in claims:
        if c.type == "ai" and c.confidence is None:
            c.confidence = "medium"
    ch.add("ai_has_confidence", "warn" if fixed else "pass",
           "Для выводов ИИ не указана уверенность — поставлено «medium»" if fixed else "У выводов ИИ указана уверенность", fixed)  # fmt: skip

    # numbers_match
    fail_paths: list[str] = []
    warn_paths: list[str] = []
    missing_numbers: list[str] = []
    for p, c in claims:
        nums = [e for ev in _cited(reg, c) for e in ev.numbers]
        absent = [m.raw for m in extract_numbers(c.text) if not number_supported(m.value, nums)]
        if absent:
            (fail_paths if c.type in ("fact", "bank") else warn_paths).append(p)
            missing_numbers.append(f"{p}: {', '.join(absent)}")
    status = "fail" if fail_paths else "warn" if warn_paths else "pass"
    ch.add("numbers_match", status,
           ("Чисел нет в процитированных источниках — " + "; ".join(missing_numbers)) if missing_numbers
           else "Числа сверены с источниками", fail_paths + warn_paths)  # fmt: skip

    # features_exist
    used = d.why_it_matters.client_features_used
    known = [k for k in used if k in inp.feature_keys]
    dropped = [k for k in used if k not in inp.feature_keys]
    d.why_it_matters.client_features_used = known
    if not known:
        ch.add(
            "features_exist",
            "fail",
            "Не указан ни один признак компании из профиля",
            ["why_it_matters.summary"],
        )
    elif dropped:
        ch.add("features_exist", "warn", f"Удалены неизвестные признаки: {', '.join(dropped)}")
    else:
        ch.add("features_exist", "pass", "Признаки компании указаны верно")

    # chain_ids_exist
    extra = [x for x in d.why_it_matters.chain_ids if x not in inp.path_ids]
    d.why_it_matters.chain_ids = [x for x in d.why_it_matters.chain_ids if x in inp.path_ids]
    ch.add("chain_ids_exist", "warn" if extra else "pass",
           f"Удалены несуществующие пути: {', '.join(extra)}" if extra else "Пути влияния указаны верно")  # fmt: skip

    # completeness
    gaps = []
    if not d.what_happened.facts:
        gaps.append("что произошло")
    if not d.why_it_matters.summary.text.strip():
        gaps.append("почему важно")
    if not d.consequences:
        gaps.append("риски и возможности")
    if not d.actions:
        gaps.append("что делать")
    ch.add("completeness", "fail" if gaps else "pass",
           f"Пустые блоки: {', '.join(gaps)}" if gaps else "Все блоки заполнены")  # fmt: skip

    # direction_consistent
    opposite = {("risk", "opportunity"), ("opportunity", "risk")}
    if inp.exposure_direction and (d.direction, inp.exposure_direction) in opposite:
        ch.add("direction_consistent", "warn",
               f"Направление «{d.direction}» противоположно расчёту путей влияния («{inp.exposure_direction}»)")  # fmt: skip
    else:
        ch.add("direction_consistent", "pass", "Направление согласовано с путями влияния")

    # impact_consistent (автоисправление)
    if inp.expected_impact is not None:
        cap = IMPACT_ORDER[min(len(IMPACT_ORDER) - 1, IMPACT_ORDER.index(inp.expected_impact) + 1)]
        if IMPACT_ORDER.index(d.impact_level) > IMPACT_ORDER.index(cap):
            ch.add("impact_consistent", "warn", f"Уровень влияния понижен с «{d.impact_level}» до «{cap}»")
            d.impact_level = cap
        else:
            ch.add("impact_consistent", "pass", "Уровень влияния согласован с ранжированием")

    # products_valid
    allowed = {c.product_id for c in inp.candidates}
    bad = []
    for i, a in enumerate(d.actions):
        if a.product_id is not None and a.product_id not in allowed:
            bad.append(f"actions[{i}].claim")
            a.product_id = None
    ch.add("products_valid", "fail" if bad else "pass",
           "Указан продукт не из списка кандидатов — удалён" if bad else "Продукты из списка кандидатов", bad)  # fmt: skip

    # no_foreign_urls
    allowed_domains = {_domain(e.url) for e in reg.all() if e.url}
    texts: list[tuple[str, str]] = [(p, c.text) for p, c in d.claims()]
    texts += [("headline", d.headline), ("why_you", d.why_you)]
    texts += [(f"consequences[{i}].claim", x.title) for i, x in enumerate(d.consequences)]
    texts += [(f"actions[{i}].claim", x.title) for i, x in enumerate(d.actions)]
    bad, found = [], []
    for p, text in texts:
        for m in _URL.finditer(text):
            if _domain(m.group(0)) not in allowed_domains:
                bad.append(p)
                found.append(m.group(0))
    ch.add("no_foreign_urls", "fail" if bad else "pass",
           f"Ссылки и домены не из источников: {', '.join(sorted(set(found)))}" if bad else "Посторонних ссылок нет",
           sorted(set(bad)))  # fmt: skip

    # banned_phrases
    hits, hit_paths = [], []
    for p, text in texts:
        for rx, label in _BANNED:
            if rx.search(text):
                hits.append(label)
                hit_paths.append(p)
    ch.add("banned_phrases", "warn" if hits else "pass",
           f"Недопустимые формулировки: {', '.join(sorted(set(hits)))} — переформулируй" if hits else "Формулировки допустимы",
           sorted(set(hit_paths)))  # fmt: skip

    # bank_view_consistency (автоисправление)
    bv = d.bank_view
    has_alfa = any(e.kind == "alfa" for e in reg.all())
    should = bool(bv.claims) and has_alfa
    notes = []
    if bv.available != should:
        notes.append(f"available → {str(should).lower()}")
        bv.available = should
    if not should and bv.alignment != "no_data":
        notes.append("alignment → no_data")
        bv.alignment = "no_data"
    if should and bv.alignment == "no_data":
        notes.append("alignment → neutral")
        bv.alignment = "neutral"
    ch.add("bank_view_consistency", "warn" if notes else "pass",
           "Позиция банка исправлена: " + ", ".join(notes) if notes else "Блок позиции банка согласован")  # fmt: skip
    return d, ch.results


def _graded(draft: InsightDraft) -> list[tuple[str, Claim]]:
    return [(p, c) for p, c in draft.claims() if c.type in ("fact", "bank")]


def supported_share(
    draft: InsightDraft, checks: list[CheckResult], verdicts: list[ClaimVerdict], llm_skipped: bool
) -> float:
    """Доля подтверждённых среди fact и bank: supported = 1, partial = 0.5; fail проверки → 0."""
    graded = _graded(draft)
    if not graded:
        return 1.0
    failed = _removable(draft, checks)
    by_path = {v.path: v.verdict for v in verdicts}
    total = 0.0
    for p, _ in graded:
        if p in failed:
            continue
        verdict = by_path.get(p)
        total += VERDICT_SCORE[verdict] if verdict else (1.0 if llm_skipped else 0.5)
    return round(total / len(graded), 4)


def _render_verify(ctx: AgentContext, draft: InsightDraft) -> tuple[list[Any], str]:
    reg = ctx.evidence
    claims = [
        {"path": p, "type": c.type, "text": c.text, "evidence": [r for r in c.refs if reg.get(r)]}
        for p, c in draft.claims()
    ]
    cited = {r for c in claims for r in c["evidence"]}
    evidence = [
        {
            "eid": e.eid, "kind": e.kind, "kind_label": reg.kind_label(e), "title": e.title,
            "untrusted": e.untrusted, "text": (e.full_text or e.text)[:VERIFY_EVIDENCE_CHARS],
        }
        for e in reg.all() if e.eid in cited
    ]  # fmt: skip
    rendered = ctx.app.prompts.render(
        "verify",
        company_name=ctx.profile.name,
        industry_name=ctx.profile.industry_name,
        claims=claims,
        evidence=evidence,
    )
    return rendered.messages, rendered.version


async def judge(
    ctx: AgentContext, draft: InsightDraft, exclude_families: list[str] | None = None
) -> VerifyLLMOutput | None:
    """LLM-судья (§9.2). None — судья недоступен (проверка продолжается без него)."""
    messages, version = _render_verify(ctx, draft)
    try:
        res = await ctx.app.router.structured(
            task="verify", messages=messages, schema=VerifyLLMOutput, prompt_version=version,
            priority=ctx.priority, run_id=ctx.run_id, exclude_families=exclude_families,
        )  # fmt: skip
    except LLMError as exc:
        log.warning("verify_judge_unavailable", run_id=ctx.run_id, error=str(exc)[:200])
        ctx.trace.emit("verify.check", "verify", "Независимая проверка недоступна — только автоматические проверки",
                       status="warn", payload={"code": "llm_judge", "status": "warn", "message": str(exc)[:200]})  # fmt: skip
        return None
    known = {p for p, _ in draft.claims()}
    out = res.value
    out.verdicts = [v for v in out.verdicts if v.path in known]
    return out


def build_issues(draft: InsightDraft, checks: list[CheckResult], verdicts: list[ClaimVerdict],
                 contradictions: list[str], missing: list[str]) -> list[str]:  # fmt: skip
    """§9.3: строка на каждый fail, partial, unsupported, contradicted; затем missing и contradictions."""
    issues: list[str] = []
    for r in checks:
        if r.status == "fail":
            issues.append(f"{', '.join(r.paths)}: {r.message}" if r.paths else r.message)
        elif r.code == "banned_phrases" and r.status == "warn":
            issues.append(f"{', '.join(r.paths)}: {r.message}")
    hint = {
        "partial": "уточни формулировку по источнику",
        "unsupported": "в источниках этого нет — убери утверждение или сошлись на подходящий источник",
        "contradicted": "источники говорят обратное — исправь утверждение",
    }
    for v in verdicts:
        if v.verdict in hint:
            comment = f" ({v.comment})" if v.comment else ""
            issues.append(f"{v.path}: {hint[v.verdict]}{comment}")
    issues += [f"Не хватает ответа: {m}" for m in missing]
    issues += [f"Противоречие: {c}" for c in contradictions]
    return issues


async def verify(
    ctx: AgentContext,
    draft: InsightDraft,
    inp: VerifyInputs,
    *,
    attempt: int = 1,
    exclude_families: list[str] | None = None,
) -> tuple[InsightDraft, VerificationReport]:
    """Полная проверка §9.1–9.3. Возвращает черновик с автоисправлениями и отчёт."""
    fixed, checks = deterministic_checks(draft, ctx.evidence, inp)
    for r in checks:
        if r.status != "pass":
            ctx.trace.emit("verify.check", "verify", r.message, status="warn" if r.status == "warn" else "error",
                           payload={"code": r.code, "status": r.status, "message": r.message})  # fmt: skip
    if not any(r.status != "pass" for r in checks):
        ctx.trace.emit(
            "verify.check", "verify", "Автоматические проверки пройдены", payload={"status": "pass"}
        )
    clean = all(r.status == "pass" for r in checks)
    skip = (
        ctx.app.settings.verify_llm_skip_if_clean
        and clean
        and len(_graded(fixed)) <= SKIP_IF_CLEAN_MAX_CLAIMS
    )
    out = None if skip else await judge(ctx, fixed, exclude_families)
    llm_skipped = out is None
    verdicts = out.verdicts if out else []
    contradictions = out.contradictions if out else []
    missing = out.missing if out else []
    share = supported_share(fixed, checks, verdicts, llm_skipped)
    passed = (
        not any(r.status == "fail" for r in checks)
        and share >= PASS_SUPPORTED_SHARE
        and not any(v.verdict == "contradicted" for v in verdicts)
        and not missing
    )
    report = VerificationReport(
        passed=passed, attempt=attempt, checks=checks, verdicts=verdicts, contradictions=contradictions,
        missing=missing, supported_share=share,
        issues=build_issues(fixed, checks, verdicts, contradictions, missing), llm_skipped=llm_skipped,
    )  # fmt: skip
    graded = len(_graded(fixed))
    ok = round(share * graded)
    ctx.trace.emit(
        "verify.report", "verify",
        f"Подтверждено {ok} из {graded} утверждений" + ("" if passed else f"; замечаний: {len(report.issues)}"),
        status="ok" if passed else "warn",
        payload={"passed": passed, "supported_share": share, "issues": report.issues[:10]},
    )  # fmt: skip
    return fixed, report


# ── деградация (§9.5) ──
@dataclass
class Degraded:
    draft: InsightDraft
    status: InsightStatus
    removed_claims: int
    supported_share: float
    warnings: list[str]


def degrade(draft: InsightDraft, report: VerificationReport) -> Degraded:
    d = draft.model_copy(deep=True)
    bad = _removable(draft, report.checks)
    bad |= {v.path for v in report.verdicts if v.verdict in ("unsupported", "contradicted")}
    needs_review = False
    removed = 0
    warnings: list[str] = []

    def demote(c: Claim) -> None:
        c.type, c.confidence = "ai", "low"

    def prune(items: list[Any], path_of: Any, claim_of: Any) -> list[Any]:
        nonlocal removed, needs_review
        keep = [x for i, x in enumerate(items) if path_of(i) not in bad]
        removed += len(items) - len(keep)
        if not keep and items:  # обязательный блок не оставляем пустым: последний элемент — как вывод ИИ
            needs_review = True
            first = items[0]
            demote(claim_of(first))
            removed -= 1
            keep = [first]
        return keep

    facts = d.what_happened.facts
    d.what_happened.facts = prune(facts, lambda i: f"what_happened.facts[{i}]", lambda x: x)
    assumptions = d.what_happened.assumptions
    kept_a = [x for i, x in enumerate(assumptions) if f"what_happened.assumptions[{i}]" not in bad]
    removed += len(assumptions) - len(kept_a)
    d.what_happened.assumptions = kept_a
    if "why_it_matters.summary" in bad:
        demote(d.why_it_matters.summary)
        needs_review = True
        warnings.append("Вывод «почему важно» не подтверждён источниками")
    d.consequences = prune(d.consequences, lambda i: f"consequences[{i}].claim", lambda x: x.claim)
    d.actions = prune(d.actions, lambda i: f"actions[{i}].claim", lambda x: x.claim)
    bclaims = d.bank_view.claims
    kept_b = [x for i, x in enumerate(bclaims) if f"bank_view.claims[{i}]" not in bad]
    removed += len(bclaims) - len(kept_b)
    d.bank_view.claims = kept_b
    if not kept_b:
        d.bank_view.available, d.bank_view.alignment = False, "no_data"
    if removed:
        warnings.append("Часть выводов скрыта: не удалось подтвердить источниками")

    # доля после удаления: вердикты переносятся по тексту утверждения (пути сдвинулись)
    by_text = {c.text: v.verdict for v in report.verdicts for p, c in draft.claims() if p == v.path}
    fails_text = {c.text for p, c in draft.claims() if p in bad}
    graded = _graded(d)
    if graded:
        total = sum(
            0.0 if c.text in fails_text
            else VERDICT_SCORE[by_text[c.text]] if c.text in by_text
            else (1.0 if report.llm_skipped else 0.5)
            for _, c in graded
        )  # fmt: skip
        share = round(total / len(graded), 4)
    else:
        share = 0.0
        needs_review = True
    status: InsightStatus = "needs_review" if needs_review or share < PUBLISH_SUPPORTED_SHARE else "published"
    return Degraded(draft=d, status=status, removed_claims=removed, supported_share=share, warnings=warnings)


def _removable(draft: InsightDraft, checks: list[CheckResult]) -> set[str]:
    """Пути с fail по проверкам, удаляющим утверждение; расхождение чисел в выводах ИИ — только warn."""
    types = {p: c.type for p, c in draft.claims()}
    out = set()
    for r in checks:
        if r.status != "fail" or r.code not in REMOVING_CHECKS:
            continue
        out |= {p for p in r.paths if not (r.code == "numbers_match" and types.get(p) == "ai")}
    return out


# ── FakeLLM: судья по маркерам ──
_CLAIM_LINE = re.compile(
    r"^\[(?P<path>[a-z_.]+(?:\[\d+\])?(?:\.claim)?)\] \((?P<type>fact|bank|ai)\) (?P<text>.*)$", re.M
)


@fake_handler("verify")
def fake_verify(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any] | None:
    """supported для всех утверждений; `[[UNSUPPORTED]]`, `[[PARTIAL]]`, `[[CONTRADICTED]]` в тексте меняют вердикт."""
    user = next(
        (m.content for m in reversed(req.messages) if m.role == "user" and isinstance(m.content, str)), ""
    )
    verdicts = []
    for m in _CLAIM_LINE.finditer(user):
        text = m.group("text")
        verdict = "supported"
        for marker in ("UNSUPPORTED", "PARTIAL", "CONTRADICTED"):
            if f"[[{marker}]]" in text:
                verdict = marker.lower()
        verdicts.append({"path": m.group("path"), "verdict": verdict,
                         "comment": "" if verdict == "supported" else "маркер теста"})  # fmt: skip
    missing = ["что делать"] if "[[MISSING]]" in user else []
    return {"verdicts": verdicts, "contradictions": [], "missing": missing}
