"""`alfa eval report`: eval/reports/latest.json и latest.md (docs/12-quality.md §5)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alfa_insight.appctx import AppContext
from alfa_insight.evaluation.dataset import Gold, read_csv
from alfa_insight.evaluation.generation_eval import VERDICT_SCORE, eval_events, evaluate_generation


def _seed_hash(app: AppContext) -> str:
    path = app.settings.seed_dir / "news.jsonl"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else ""


def human_grounding(path: Path) -> dict[str, float | int | None]:
    """Ручная проверка выборки утверждений: доля подтверждённых и согласие с судьёй."""
    rows = [r for r in read_csv(path) if r.get("human_verdict")]
    if not rows:
        return {"grounded_share_human": None, "judge_agreement": None, "human_checked": 0}
    human = [VERDICT_SCORE.get(r["human_verdict"].strip(), 0.0) for r in rows]
    agree = [r["human_verdict"].strip() == r["llm_verdict"].strip() for r in rows]
    return {
        "grounded_share_human": round(sum(human) / len(human), 4),
        "judge_agreement": round(sum(agree) / len(agree), 4),
        "human_checked": len(rows),
    }


def build_report(app: AppContext, gold: Gold, ranking: dict[str, Any], eval_dir: Path) -> dict[str, Any]:
    pairs = eval_events(app, gold)
    generation = {**evaluate_generation(app, pairs), **human_grounding(eval_dir / "grounding_check.csv")}
    analyze_path = eval_dir / "reports" / "analyze.json"
    analyze = json.loads(analyze_path.read_text(encoding="utf-8")) if analyze_path.exists() else None
    labels = list(gold.labels.values())
    cfg = app.router.config
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": {
            "companies": len({x.company_id for x in labels}),
            "judgements": len(labels),
            "labels_source": gold.source,
            "human_labeled": sum(1 for x in labels if x.human),
            "kappa": round(gold.kappa, 4) if gold.kappa is not None else None,
            "kappa_overlap": gold.overlap,
            "seed_hash": _seed_hash(app),
        },
        "ranking": ranking,
        "generation": generation,
        "analyze": analyze,
        "config": {
            "ranking_version": app.ranking_config.version,
            "channel_weights": dict(app.ranking_config.channel_weights),
            "prompt_versions": {
                k: app.prompts.version(k) for k in ("tagging", "draft", "agent", "verify", "eval_label")
            },
            "models": {t: cfg.tasks[t].chain for t in ("tagging", "draft", "agent", "verify", "eval_label")},
            "llm_mode": app.settings.llm_mode,
        },
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def to_markdown(rep: dict[str, Any]) -> str:
    ds, rk, gen = rep["dataset"], rep["ranking"], rep["generation"]
    src = {"human": "ручная разметка", "llm": "предразметка LLM (до ручной проверки)", "none": "нет разметки"}
    lines = [
        "# Офлайн-оценка «Альфа Инсайт»",
        "",
        f"Сформирован {rep['generated_at']}. Набор: {ds['companies']} компаний, {ds['judgements']} суждений, "
        f"источник оценок — {src[ds['labels_source']]}; каппа {_fmt(ds['kappa'])} ({ds['kappa_overlap']} общих).",
        "",
        "## Ранжирование: цепная реакция против базовых вариантов",
        "",
        "| Вариант | nDCG@5 | P@5 | Recall(rel=3)@5 | Spearman | Направление |",
        "|---|---|---|---|---|---|",
        f"| **Альфа Инсайт (цепная реакция)** | **{_fmt(rk.get('ndcg@5'))}** | {_fmt(rk.get('p@5'))} | "
        f"{_fmt(rk.get('recall_rel3@5'))} | {_fmt(rk.get('spearman'))} | {_fmt(rk.get('direction_acc'))} |",
    ]
    names = {
        "industry_only": "Только своя отрасль",
        "no_payments": "Без платёжных данных",
        "random": "Случайный порядок",
    }
    for key in ("industry_only", "no_payments", "random"):
        b = rk.get("baselines", {}).get(key, {})
        lines.append(f"| {names[key]} | {_fmt(b.get('ndcg@5'))} | {_fmt(b.get('p@5'))} | {_fmt(b.get('recall_rel3@5'))} | "
                     f"{_fmt(b.get('spearman'))} | {_fmt(b.get('direction_acc'))} |")  # fmt: skip
    med = rk.get("score_medians_by_rel", {})
    lines += [
        "",
        "Медианы скора по оценкам: " + ", ".join(f"rel={k}: {_fmt(v)}" for k, v in med.items()) + ".",
        "",
        "| Компания | nDCG@5 | P@5 |",
        "|---|---|---|",
        *[
            f"| {c} | {_fmt(v.get('ndcg@5'))} | {_fmt(v.get('p@5'))} |"
            for c, v in rk.get("per_company", {}).items()
        ],
        "",
        "## Генерация",
        "",
        "| Метрика | Значение | Цель |",
        "|---|---|---|",
        f"| Инсайтов в оценке | {gen['insights']} из {gen['planned']} | 18 |",
        f"| Обоснованность (судья) | {_fmt(gen['grounded_share_llm'])} | ≥ 0.85 |",
        f"| Обоснованность (человек, выборка {gen.get('human_checked', 0)}) | {_fmt(gen.get('grounded_share_human'))} | ≥ 0.8 |",
        f"| Согласие судьи и человека | {_fmt(gen.get('judge_agreement'))} | — |",
        f"| Полнота 6 блоков | {_fmt(gen['completeness'])} | 1.0 |",
        f"| Противоречия | {_fmt(gen['contradiction_rate'])} | ≤ 0.1 |",
        f"| Персонализация | {_fmt(gen['personalization_rate'])} | ≥ 0.9 |",
        f"| Числа сверены | {_fmt(gen['numbers_match_rate'])} | ≥ 0.95 |",
        f"| На проверке у эксперта | {_fmt(gen['needs_review_share'])} | ≤ 0.1 |",
        f"| Время, p50 / p95, мс | {_fmt(gen['latency_ms']['p50'])} / {_fmt(gen['latency_ms']['p95'])} | p50 ≤ 12 000 |",
        f"| Стоимость инсайта, ₽ | {_fmt(gen['cost_rub_mean'])} | — |",
    ]
    an = rep.get("analyze")
    if an:
        lines += ["", "## Фича B: свежие ссылки", "",
                  f"Прогонов {an['runs']}, успешных {_fmt(an['success_rate'])}, "
                  f"p50 {_fmt(an['latency_ms']['p50'])} мс, p95 {_fmt(an['latency_ms']['p95'])} мс."]  # fmt: skip
    return "\n".join(lines) + "\n"
