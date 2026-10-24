"""Текстовые блоки для промптов и evidence: профиль, пути влияния (docs/05-prompts.md §6)."""

from __future__ import annotations

from collections.abc import Iterable

from alfa_insight.agent.evidence import EvidenceItem
from alfa_insight.data.factors import exposure_level
from alfa_insight.data.models import CompanyProfile, IndustryShare
from alfa_insight.data.profiles import BUCKET_RU, DIRECTION_RU, PRODUCT_NAMES, pct
from alfa_insight.llm.prompts import PromptLoader, sanitize_untrusted
from alfa_insight.ranking.chain import strength_label
from alfa_insight.ranking.effects import DIRECTION_RU as IMPACT_RU
from alfa_insight.ranking.effects import EFFECT_SHORT
from alfa_insight.ranking.models import ChainPath
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.text.normalize import lower_name

MIX_LABEL_TOP = 5
CHAIN_BLOCK_PATHS = 6
CHANNEL_RU = {"own": "ваша отрасль", "supply": "поставщики", "demand": "покупатели", "factor": "фактор"}


def money_bn(value: float) -> str:
    return f"{value / 1e9:.1f}".replace(".", ",") + " млрд ₽"


def revenue_label(p: CompanyProfile) -> str:
    return f"≈ {money_bn(p.revenue_rub)}" if p.revenue_rub else BUCKET_RU[p.revenue_bucket]


def products_label(p: CompanyProfile) -> str:
    return ", ".join(PRODUCT_NAMES.get(code, code) for code, info in p.products.items() if info.has)


def ved_label(p: CompanyProfile) -> str:
    parts = []
    for v in p.ved:
        cur = f", {'/'.join(v.currencies)}" if v.currencies else ""
        parts.append(f"{v.country_name} ({DIRECTION_RU[v.direction]}{cur})")
    return "; ".join(parts)


def mix_label(mix: list[IndustryShare], prior: dict[str, float], coverage: float, tax: Taxonomy) -> str:
    if coverage > 0 and mix:
        top = sorted(mix, key=lambda s: -s.share_total)[:MIX_LABEL_TOP]
        return ", ".join(f"{lower_name(s.name)} {pct(s.share_total)}" for s in top)
    if prior:
        top_prior = sorted(prior.items(), key=lambda kv: -kv[1])[:MIX_LABEL_TOP]
        return "нет данных; типично для отрасли: " + ", ".join(
            f"{lower_name(tax.industry(i).name)} ≈ {pct(v)}" for i, v in top_prior
        )
    return "нет данных"


def factors_label(p: CompanyProfile) -> str:
    items = sorted(p.factor_exposure, key=lambda f: -f.exposure)
    return "; ".join(
        f"{f.name} — {exposure_level(f.exposure)}" + (f" ({', '.join(f.reasons[:2])})" if f.reasons else "")
        for f in items
    )


def overrides_label(p: CompanyProfile) -> str:
    parts = [
        f"{f.label}: {f.value}" for f in p.features if f.source == "override" and f.key != "override.notes"
    ]
    if p.notes:
        parts.append(p.notes)
    return "; ".join(parts)


def profile_brief(prompts: PromptLoader, tax: Taxonomy, p: CompanyProfile) -> str:
    buyers = (
        "направление платежей не определено"
        if p.direction_unknown
        else mix_label(p.buyers_mix, tax.typical_buyers(p.industry_id), p.coverage.get("demand", 0.0), tax)
    )
    return prompts.render_part(
        "_profile.j2",
        p=p,
        pct=pct,
        revenue_label=revenue_label(p),
        products_label=products_label(p),
        ved_label=ved_label(p),
        suppliers_label=mix_label(
            p.suppliers_mix, tax.typical_suppliers(p.industry_id), p.coverage.get("supply", 0.0), tax
        ),
        buyers_label=buyers,
        factors_label=factors_label(p) or "нет выраженной",
        overrides_label=overrides_label(p),
    )


def path_weight_label(path: ChainPath) -> str:
    if path.level == 2 and path.via_industry_name:
        via = f"доля закупок у отрасли «{path.via_industry_name}» {pct(path.raw_share) if path.raw_share is not None else '≈ ' + pct(path.company_weight / (path.via_share or 1))}"
        return f"второй уровень: {via}, а {path.industry_name} — около {pct(path.via_share or 0)} закупок этой отрасли (типовые доли)"
    if path.channel in ("supply", "demand"):
        what = "закупок" if path.channel == "supply" else "продаж"
        if path.basis == "prior" or path.raw_share is None:
            return f"типичная доля {what} ≈ {pct(path.company_weight)} (данных о платежах нет)"
        cov = f" (покрытие {pct(path.coverage)})" if path.coverage is not None else ""
        return f"доля {what} {pct(path.raw_share)}{cov}"
    if path.channel == "own":
        return "основная отрасль" if path.basis == "main_industry" else "дополнительная отрасль"
    reasons = f" ({', '.join(path.reasons[:2])})" if path.reasons else ""
    return f"чувствительность компании {strength_label(path.company_weight)}{reasons}"


def path_line(path: ChainPath, eid: str | None) -> str:
    """`P1 [E4] поставщики · Металлургия · prices_up · доля закупок 34% (покрытие 90%) · сила связи средняя · риск · …`."""
    ref = f" [{eid}]" if eid else ""
    if path.channel == "factor":
        arrow = "рост" if (path.factor_direction or 1) > 0 else "снижение"
        what = f"{path.factor_name} · {arrow}"
    elif path.level == 2:
        what = f"{path.industry_name} → {path.via_industry_name} · {path.effect}"
    else:
        what = f"{path.industry_name} · {path.effect}"
    return (
        f"{path.id}{ref} {CHANNEL_RU[path.channel]} · {what} · {path_weight_label(path)} · "
        f"сила связи {strength_label(path.contribution)} · {IMPACT_RU[path.direction]} · {path.mechanism}"
    )


def path_text(path: ChainPath) -> str:
    """Текст evidence пути влияния: что видит модель и с чем сверяются числа."""
    if path.channel == "factor":
        arrow = "рост" if (path.factor_direction or 1) > 0 else "снижение"
        head = f"Фактор «{path.factor_name}»: событие означает {arrow}."
    elif path.level == 2:
        head = (
            f"Отрасль «{path.industry_name}» — поставщик ваших поставщиков (отрасль «{path.via_industry_name}»): "
            f"{EFFECT_SHORT.get(path.effect or '', path.effect or '')}."
        )
    else:
        head = (
            f"Отрасль «{path.industry_name}» ({CHANNEL_RU[path.channel]}): "
            f"{EFFECT_SHORT.get(path.effect or '', path.effect or '')}."
        )
    parts = [head, f"Связь с компанией: {path_weight_label(path)}."]
    if path.top_counterparties:
        tops = ", ".join(f"{c.name} — {pct(c.share)}" for c in path.top_counterparties)
        parts.append(f"Крупнейшие контрагенты отрасли: {tops}.")
    parts.append(
        f"Сила связи: {strength_label(path.contribution)}. {IMPACT_RU[path.direction].capitalize()}: {path.mechanism}."
    )
    return " ".join(parts)


def chain_block(paths: Iterable[ChainPath], path_eids: dict[str, str]) -> str:
    lines = [path_line(p, path_eids.get(p.id)) for p in list(paths)[:CHAIN_BLOCK_PATHS]]
    return (
        "\n".join(lines) if lines else "Путей влияния не найдено: событие слабо связано с данными компании."
    )


def untrusted_wrap(item: EvidenceItem, text: str | None = None) -> str:
    body = text if text is not None else item.text
    if not item.untrusted:
        return body
    return f'<untrusted_document id="{item.eid}" kind="{item.kind}">\n{sanitize_untrusted(body)}\n</untrusted_document>'


def evidence_block(items: Iterable[EvidenceItem], kind_label: dict[str, str]) -> str:
    """Формат evidence из `draft.user.j2` (05-prompts.md §8) — для agent.user и revise."""
    out = []
    for e in items:
        head = f"[{e.eid}] {kind_label.get(e.kind, e.kind)} · {e.title}"
        if e.publisher:
            head += f" · {e.publisher}"
        if e.published_at:
            head += f" · {e.published_at.date().isoformat()}"
        out.append(f"{head}\n{untrusted_wrap(e)}")
    return "\n\n".join(out)
