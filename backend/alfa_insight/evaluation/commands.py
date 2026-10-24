"""`alfa eval`: офлайн-оценка качества (docs/12-quality.md §8)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import typer

eval_app = typer.Typer(help="Офлайн-оценка качества.", no_args_is_help=True)


def _ctx():  # type: ignore[no-untyped-def]
    from alfa_insight.appctx import build_context

    return build_context()


def _companies(app, spec: str) -> list[str]:  # type: ignore[no-untyped-def]
    from alfa_insight.services.jobs import precompute_companies

    return precompute_companies(app, spec)


def _pool(app, companies: list[str], rebuild: bool = False) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    from alfa_insight.evaluation.dataset import POOL_FIELDS, build_pool, eval_dir, read_csv, write_csv

    path = eval_dir(app) / "pool.csv"
    rows = [] if rebuild else read_csv(path)
    have = {r["company_id"] for r in rows}
    missing = [c for c in companies if c not in have]
    if missing:
        rows += build_pool(app, missing)
        write_csv(path, rows, POOL_FIELDS)
        typer.echo(f"{path}: пул для {', '.join(missing)}")
    return [r for r in rows if r["company_id"] in companies]


def _gold(app):  # type: ignore[no-untyped-def]
    from alfa_insight.evaluation.dataset import eval_dir, gold_labels, read_labels

    return gold_labels(read_labels(eval_dir(app) / "labels.csv"))


@eval_app.command("prelabel")
def prelabel_cmd(
    companies: str = typer.Option("demo", "--companies"),
    max_cost: float = typer.Option(5.0, "--max-cost", help="Лимит стоимости, ₽"),
    rebuild_pool: bool = typer.Option(False, "--rebuild-pool", help="Пересобрать пул кандидатов"),
) -> None:
    """LLM-предразметка пула (labeler=llm) для пар, которых ещё нет в eval/labels.csv."""
    from alfa_insight.evaluation.dataset import eval_dir, read_labels, write_labels
    from alfa_insight.evaluation.labeling import prelabel_company

    app = _ctx()
    ids = _companies(app, companies)
    pool = _pool(app, ids, rebuild_pool)
    path = eval_dir(app) / "labels.csv"
    labels = read_labels(path)
    done = {(x.company_id, x.seed_id) for x in labels if x.labeler == "llm"}
    spent = 0.0
    for cid in ids:
        todo = [r["seed_id"] for r in pool if r["company_id"] == cid and (cid, r["seed_id"]) not in done]
        if not todo:
            continue
        if spent >= max_cost:
            typer.echo(f"лимит {max_cost} ₽ исчерпан, остальные компании пропущены")
            break
        new, cost = asyncio.run(prelabel_company(app, cid, todo))
        spent += cost
        labels += new
        write_labels(path, labels)
        typer.echo(f"{cid}: размечено {len(new)} из {len(todo)}, {cost:.2f} ₽")
    typer.echo(f"{path}: строк {len(labels)}, потрачено {spent:.2f} ₽")


@eval_app.command("label")
def label_cmd(
    company: str = typer.Option(..., "--company"),
    labeler: str = typer.Option(..., "--labeler", help="Имя разметчика; строка станет human:<имя>"),
) -> None:
    """Интерактивная разметка пула компании. Наш скор не показывается; предразметка — подсказка."""
    from alfa_insight.agent.render import profile_brief
    from alfa_insight.evaluation.dataset import Label, eval_dir, read_labels, write_labels
    from alfa_insight.evaluation.labeling import event_card

    app = _ctx()
    pool = _pool(app, [company])
    path = eval_dir(app) / "labels.csv"
    labels = read_labels(path)
    who = f"human:{labeler}"
    mine = {x.seed_id for x in labels if x.company_id == company and x.labeler == who}
    hints = {x.seed_id: x for x in labels if x.company_id == company and x.labeler == "llm"}
    todo = [r for r in pool if r["seed_id"] not in mine]
    typer.echo(profile_brief(app.prompts, app.taxonomy, app.profiles.get(company)))
    typer.echo(
        "\nОценка: 0 — не влияет, 1 — слабо, 2 — заметно, 3 — сильно и прямо; s — пропустить, q — выйти."
    )
    dirs = {"r": "risk", "o": "opportunity", "m": "mixed"}
    for i, r in enumerate(todo, 1):
        typer.echo(f"\n[{i}/{len(todo)}] {event_card(app, r['seed_id'])}")
        if r["seed_id"] in hints:
            h = hints[r["seed_id"]]
            typer.echo(f"Подсказка LLM: {h.relevance}, {h.direction} — {h.notes}")
        answer = typer.prompt("Оценка", default="s").strip().lower()
        if answer == "q":
            break
        if answer not in ("0", "1", "2", "3"):
            continue
        rel = int(answer)
        direction = "none"
        if rel > 0:
            direction = dirs.get(typer.prompt("Направление r/o/m", default="r").strip().lower()[:1], "mixed")
        notes = typer.prompt("Комментарий", default="").strip()
        labels.append(Label(company, r["seed_id"], rel, direction, who, notes))  # type: ignore[arg-type]
        write_labels(path, labels)
    typer.echo(f"{path}: размечено {who}: {sum(1 for x in labels if x.labeler == who)}")


@eval_app.command("ranking")
def ranking_cmd(baselines: bool = typer.Option(False, "--baselines")) -> None:
    """nDCG@5, P@5, Recall@5, Spearman, точность направления; с --baselines — базовые варианты."""
    from alfa_insight.evaluation.ranking_eval import evaluate_ranking

    app = _ctx()
    gold = _gold(app)
    res = evaluate_ranking(app, gold, baselines=baselines)
    typer.echo(
        f"разметка: {gold.source}, суждений {len(gold.labels)}, без события в базе {res['missing_events']}"
    )
    keys = ["ndcg@5", "p@5", "recall_rel3@5", "spearman", "direction_acc"]
    typer.echo("ours:          " + "  ".join(f"{k}={res[k]}" for k in keys))
    for name, b in res.get("baselines", {}).items():
        typer.echo(f"{name:14} " + "  ".join(f"{k}={b.get(k)}" for k in keys if k in b))
    typer.echo(f"медианы скора по rel: {res['score_medians_by_rel']}")


@eval_app.command("generate")
def generate_cmd(
    top: int = typer.Option(3, "--top"),
    max_cost: float = typer.Option(20.0, "--max-cost", help="Лимит стоимости, ₽"),
) -> None:
    """Инсайты (pipeline) для `top` событий rel ≥ 2 каждой компании, которых ещё нет."""
    from alfa_insight.evaluation.generation_eval import enqueue_missing, eval_events
    from alfa_insight.services.jobs import JobRunner

    app = _ctx()
    pairs = eval_events(app, _gold(app), top)
    queued = enqueue_missing(app, pairs)
    limit = max(0, min(queued, int(max_cost / 0.8)))  # ≈ 0.8 ₽ на инсайт с запасом
    typer.echo(f"событий в оценке {len(pairs)}, без инсайта {queued}, запускаю {limit}")
    if limit:
        done = asyncio.run(JobRunner(app).process_queue(limit=limit))
        typer.echo(f"выполнено прогонов: {done}")


@eval_app.command("grounding-check")
def grounding_check_cmd(
    sample: int = typer.Option(20, "--sample"),
    force: bool = typer.Option(False, "--force", help="Перезаписать, даже если есть ручные вердикты"),
) -> None:
    """Выборка утверждений fact и bank в eval/grounding_check.csv для ручной проверки (human_verdict)."""
    from alfa_insight.evaluation.dataset import eval_dir, read_csv, write_csv
    from alfa_insight.evaluation.generation_eval import eval_events, sample_claims

    app = _ctx()
    path = eval_dir(app) / "grounding_check.csv"
    if not force and any(r.get("human_verdict") for r in read_csv(path)):
        typer.echo(f"{path}: уже есть ручные вердикты, --force для перезаписи")
        raise typer.Exit(1)
    rows = sample_claims(app, eval_events(app, _gold(app)), sample)
    fields = ["insight_id", "path", "type", "text", "sources", "llm_verdict", "human_verdict"]
    write_csv(path, rows, fields)
    typer.echo(
        f"{path}: утверждений {len(rows)}; заполните human_verdict: supported | partial | unsupported | contradicted"
    )


@eval_app.command("analyze-urls")
def analyze_urls_cmd(path: Path = typer.Argument(..., help="Файл: по ссылке в строке")) -> None:
    """Фича B на свежих ссылках: доля успешных прогонов, p50 и p95 полного времени → eval/reports/analyze.json."""
    from alfa_insight.agent.intake import AnalyzeInput
    from alfa_insight.evaluation import metrics as m
    from alfa_insight.evaluation.dataset import eval_dir
    from alfa_insight.services.jobs import JobRunner
    from alfa_insight.store.runs import RunStore

    app = _ctx()
    urls = [
        u.strip()
        for u in path.read_text(encoding="utf-8").splitlines()
        if u.strip() and not u.startswith("#")
    ]
    companies = app.demo.ids()
    items: list[dict[str, Any]] = []

    async def run_all() -> None:
        runner = JobRunner(app)
        for i, url in enumerate(urls):
            t = time.monotonic()
            rid = runner.start_analyze(companies[i % len(companies)], "cfo", AnalyzeInput(url=url))  # type: ignore[arg-type]
            await runner.wait_all()
            run = RunStore(app.db).get(rid)
            assert run is not None
            items.append({"url": url, "status": run.status, "error_code": run.error_code,
                          "ms": int((time.monotonic() - t) * 1000), "cost_rub": round(run.cost_rub, 4)})  # fmt: skip
            typer.echo(f"{items[-1]['ms'] / 1000:5.1f} с {run.status} {run.error_code or ''} {url}")

    asyncio.run(run_all())
    ok = [x["ms"] for x in items if x["status"] == "succeeded"]
    clear = [
        x
        for x in items
        if x["status"] == "succeeded"
        or x["error_code"] in ("fetch_failed", "unsupported_content", "blocked_url")
    ]
    report: dict[str, Any] = {
        "runs": len(items), "success_rate": round(len(ok) / len(items), 4) if items else None,
        "clear_outcome_rate": round(len(clear) / len(items), 4) if items else None,
        "latency_ms": {"p50": m.percentile(ok, 0.5), "p95": m.percentile(ok, 0.95)}, "items": items,
    }  # fmt: skip
    out = eval_dir(app) / "reports" / "analyze.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"{out}: успешных {len(ok)} из {len(items)}, p50 {report['latency_ms']['p50']} мс")


@eval_app.command("report")
def report_cmd() -> None:
    """Собрать eval/reports/latest.json и latest.md (ранжирование с базовыми вариантами, генерация, фича B)."""
    from alfa_insight.evaluation.dataset import eval_dir
    from alfa_insight.evaluation.ranking_eval import evaluate_ranking
    from alfa_insight.evaluation.report import build_report, to_markdown

    app = _ctx()
    gold = _gold(app)
    out = eval_dir(app) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    rep = build_report(app, gold, evaluate_ranking(app, gold), eval_dir(app))
    (out / "latest.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "latest.md").write_text(to_markdown(rep), encoding="utf-8")
    typer.echo(to_markdown(rep))


@eval_app.command("tune")
def tune_cmd(step: float = typer.Option(0.25, "--step", help="Шаг сетки весов (по умолчанию 0.25)")) -> None:
    """Перебор весов каналов: предлагаемый diff config/ranking.yaml, человек применяет вручную."""
    from alfa_insight.evaluation.tune import tune, with_feedback

    app = _ctx()
    res = tune(app, with_feedback(app, _gold(app)), step)
    typer.echo(f"было:  {res['base']}  цель={res['objective_base']}")
    typer.echo(f"стало: {res['best']}  цель={res['objective_best']}")
    if res["best"] != res["base"]:
        typer.echo("diff config/ranking.yaml:")
        typer.echo(f"- channel_weights: {res['base']}")
        typer.echo(f"+ channel_weights: {res['best']}")
    else:
        typer.echo("текущие веса оптимальны на этих данных")
