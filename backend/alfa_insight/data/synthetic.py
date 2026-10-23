"""Генератор синтетических CSV с той же логической схемой, что и реальные данные (docs/03-data.md §8).

Детерминирован: один `seed` — побайтно одинаковые файлы. Демо-компании строятся точно по долям из
`config/demo.yaml`, остальные целевые — по типовым долям отрасли с шумом Дирихле.
"""

from __future__ import annotations

import csv
import io
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from alfa_insight.config_models import DemoCompany, DemoConfig
from alfa_insight.data.naming import match_name_industry
from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy

TARGET_REVENUE = 15_000_000_000.0
N_TARGETS = 40
CLIENT_SHARE_TARGETS = 0.94
CREDIT_SHARE, LEASING_SHARE, VED_SHARE = 0.43, 0.62, 0.50
OUT_OF_TABLE_SHARE = 0.15
DIRICHLET_ALPHA = 2.0
PERIOD = "2025"

# Отрасли нецелевых целевых компаний по группам (docs/03-data.md §8.1)
WHOLESALE = [
    "wholesale_metals",
    "wholesale_fuel",
    "wholesale_construction_materials",
    "wholesale_agri_food",
    "wholesale_consumer_goods",
    "wholesale_tech_equipment",
]
CONSTRUCTION = ["construction_buildings", "construction_infrastructure", "construction_specialized"]
AUTO = ["auto_trade"]
OTHER = [
    "metallurgy",
    "chemicals",
    "transport_logistics",
    "food_production",
    "oil_refining",
    "machinery",
    "power_utilities",
    "retail",
]
GROUP_COUNTS = {"wholesale": 22, "construction": 7, "auto": 4, "other": 7}

VED_COUNTRIES = [  # (сырая строка ФНС, вес)
    ("КИТАЙ", 0.30),
    ("Китайская Народная Республика", 0.15),
    ("ТУРЦИЯ", 0.15),
    ("ОАЭ", 0.12),
    ("ИНДИЯ", 0.08),
    ("КАЗАХСТАН", 0.08),
    ("УЗБЕКИСТАН", 0.04),
    ("БЕЛАРУСЬ", 0.04),
    ("ГОНКОНГ", 0.04),
]
DEMO_COUNTRY_RAW = {"CN": "КИТАЙ", "KZ": "КАЗАХСТАН", "IN": "ИНДИЯ", "TR": "ТУРЦИЯ", "AE": "ОАЭ"}

REGIONS = [
    ("RU-MOW", "Москва"),
    ("RU-SPE", "Санкт-Петербург"),
    ("RU-MOS", "Московская область"),
    ("RU-SVE", "Свердловская область"),
    ("RU-NVS", "Новосибирская область"),
    ("RU-KDA", "Краснодарский край"),
    ("RU-TA", "Республика Татарстан"),
    ("RU-SAM", "Самарская область"),
    ("RU-CHE", "Челябинская область"),
    ("RU-ROS", "Ростовская область"),
    ("RU-NIZ", "Нижегородская область"),
    ("RU-BA", "Республика Башкортостан"),
    ("RU-IRK", "Иркутская область"),
    ("RU-KYA", "Красноярский край"),
    ("RU-PRI", "Приморский край"),
]

ROOTS: dict[str, list[str]] = {
    "agriculture": ["Агро", "Зерно", "Нива"],
    "food_production": ["Продукт", "Хлебо", "Молоко"],
    "oil_gas": ["Нефтегаз", "Недра"],
    "coal": ["Уголь"],
    "mining_metal_ores": ["Руда", "Щебень"],
    "oil_refining": ["Нефтепродукт", "Бензин"],
    "power_utilities": ["Энергосбыт", "Электроэнергия"],
    "water_waste": ["Водоканал"],
    "textile_apparel": ["Текстиль", "Швейный"],
    "wood_paper": ["Пиломатериал", "Картон"],
    "chemicals": ["Полимер", "Химпром"],
    "pharma": ["Фарм", "Препарат"],
    "plastics_rubber": ["Пластик", "Упаковка"],
    "building_materials": ["Цемент", "Бетон", "Кирпич"],
    "metallurgy": ["Металл", "Сталь", "Прокат"],
    "metal_products": ["Металлоконструкция", "Метизы"],
    "electronics": ["Электроника"],
    "electrical_equipment": ["Кабель", "Трансформатор"],
    "machinery": ["Станок", "Спецтехника"],
    "automotive_manufacturing": ["Автозавод"],
    "other_transport_equipment": ["Вагон", "Верфь"],
    "furniture_other_manufacturing": ["Мебель"],
    "construction_buildings": ["Застройщик", "Девелопер"],
    "construction_infrastructure": ["Дорога", "Мост"],
    "construction_specialized": ["Монтаж", "Отделка"],
    "real_estate": ["Недвижимость", "Аренда"],
    "auto_trade": ["Автосалон", "Дилер", "Запчасть"],
    "wholesale_agri_food": ["Зерно", "Продукты"],
    "wholesale_consumer_goods": ["Дистрибуция", "Косметика"],
    "wholesale_tech_equipment": ["Оборудование", "Импорт"],
    "wholesale_fuel": ["Топливо", "Дизель"],
    "wholesale_metals": ["Металлобаза", "Металлопрокат", "Арматура"],
    "wholesale_construction_materials": ["Стройматериалы", "Сантехника"],
    "wholesale_chemicals": ["Удобрения", "Реагенты"],
    "wholesale_other": ["Опт", "Дистрибьютор"],
    "retail": ["Магазин", "Ритейл"],
    "transport_logistics": ["Логистика", "Перевозка", "Контейнер"],
    "hospitality": ["Ресторан", "Отель"],
    "it_telecom": ["Софт", "Связь"],
    "finance_insurance": ["Лизинг", "Страхование", "Кредит"],
    "business_services": ["Консалтинг", "Аудит", "Клининг"],
    "public_social": ["Больница", "Школа"],
    "other_services": ["Услуги", "Ремонт"],
}
NEUTRAL_ROOTS = [
    "Альтаир",
    "Вектор",
    "Гранит",
    "Зенит",
    "Орион",
    "Меридиан",
    "Радуга",
    "Сириус",
    "Феникс",
    "Лотос",
]
SUFFIXES = ["Трейд", "Снаб", "Пром", "Групп", "Инвест", "Ресурс"]
CITIES = ["Москва", "Казань", "Самара", "Пермь", "Тула", "Омск", "Уфа", "Тверь", "Курск", "Сочи"]
SURNAMES = ["Петров", "Соколов", "Морозов", "Волков", "Зайцев", "Лебедев", "Козлов", "Новиков"]
BRAND_STOPLIST = [
    "северсталь",
    "ммк",
    "нлмк",
    "евраз",
    "мечел",
    "лукойл",
    "роснефть",
    "газпром",
    "сбер",
    "втб",
    "альфа",
    "магнит",
    "лента",
    "ашан",
    "пятерочка",
    "камаз",
    "автоваз",
    "ржд",
    "аэрофлот",
    "росатом",
]

OTHER_PRODUCTS = ["deposit", "guarantee", "salary", "acquiring", "fx"]


@dataclass
class Company:
    company_id: str
    inn: str
    name: str
    okved: str
    industry_id: str
    region_code: str
    region_name: str
    revenue_rub: float
    employees: int
    is_client: bool
    group_id: str
    products: dict[str, float | None] = field(default_factory=dict)
    ved: list[tuple[str, str]] = field(default_factory=list)  # (country_raw, direction)


@dataclass
class Counterparty:
    counterparty_id: str
    inn: str
    name: str
    okved: str  # заполняется только у части внешних контрагентов (каскад payments_okved)
    industry_id: str


def inn10(rng: random.Random) -> str:
    """ИНН юрлица с кодом региона 00 (не существует) и верной контрольной цифрой."""
    digits = [0, 0] + [rng.randint(0, 9) for _ in range(7)]
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    check = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11 % 10
    return "".join(map(str, [*digits, check]))


def inn12(rng: random.Random) -> str:
    """ИНН индивидуального предпринимателя (12 цифр, регион 00, две контрольные цифры)."""
    digits = [0, 0] + [rng.randint(0, 9) for _ in range(8)]
    w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    c1 = sum(d * w for d, w in zip(digits, w1, strict=True)) % 11 % 10
    w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    c2 = sum(d * w for d, w in zip([*digits, c1], w2, strict=True)) % 11 % 10
    return "".join(map(str, [*digits, c1, c2]))


def dirichlet(rng: random.Random, alphas: list[float]) -> list[float]:
    draws = [rng.gammavariate(max(a, 1e-3), 1.0) for a in alphas]
    total = sum(draws)
    return [d / total for d in draws]


class SyntheticGenerator:
    def __init__(self, taxonomy: Taxonomy, demo: DemoConfig, *, seed: int = 42, companies: int = 3000):
        self.tax = taxonomy
        self.demo = demo
        self.rng = random.Random(seed)
        self.n_companies = companies
        self.companies: list[Company] = []
        self.by_industry: dict[str, list[Company]] = {}
        self.external: dict[str, Counterparty] = {}
        self.payments: list[tuple[str, Counterparty, str, float, int]] = []
        self._seq = 0
        self._ext_seq = 0
        self._names: set[str] = set()
        self._okved_cache: dict[str, list[str]] = {}

    # ── имена и коды ──
    def _name(self, industry_id: str | None, *, neutral: bool = False) -> str:
        for _ in range(200):
            roots = NEUTRAL_ROOTS if neutral or not industry_id else ROOTS.get(industry_id, NEUTRAL_ROOTS)
            root = self.rng.choice(roots)
            suffix = self.rng.choice(SUFFIXES)
            form = self.rng.choice(["ООО", "АО", "ООО", "ООО"])
            name = f"{form} «{root}{suffix} {self.rng.choice(CITIES)}»"
            if name in self._names:
                name = f"{form} «{root}{suffix} {self.rng.choice(CITIES)}-{self.rng.randint(2, 99)}»"
            low = name.lower()
            expected = None if neutral or not industry_id else industry_id
            if (
                name not in self._names
                and not any(b in low for b in BRAND_STOPLIST)
                and (expected is None or match_name_industry(name, self.tax) in (expected, None))
                and (expected is not None or match_name_industry(name, self.tax) is None)
            ):
                self._names.add(name)
                return name
        raise RuntimeError("не удалось подобрать уникальное название")

    def _okved_for(self, industry_id: str) -> str:
        prefixes = self.tax.industry(industry_id).okved_prefixes
        for _ in range(100):
            prefix = self.rng.choice(prefixes)
            parts = prefix.split(".")
            if len(parts) == 1:
                code = f"{prefix}.{self.rng.randint(1, 3)}{self.rng.randint(0, 9)}"
            elif len(parts[1]) == 1:
                code = f"{prefix}{self.rng.randint(1, 9)}"
            else:
                code = prefix if self.rng.random() < 0.4 else f"{prefix}.{self.rng.randint(1, 9)}"
            if self.tax.match_okved(code) == industry_id:
                return code
        raise RuntimeError(f"не удалось подобрать ОКВЭД для {industry_id}")

    def _new_company(
        self, industry_id: str, revenue: float, *, cid: str | None = None, name: str | None = None
    ) -> Company:
        if cid is None:
            self._seq += 1
            cid = f"SYN-{self._seq:06d}"
        region_code, region_name = self.rng.choice(REGIONS)
        employees = max(5, int(revenue / self.rng.uniform(8e6, 3e7)))
        company = Company(
            company_id=cid,
            inn=inn10(self.rng),
            name=name or self._name(industry_id),
            okved=self._okved_for(industry_id),
            industry_id=industry_id,
            region_code=region_code,
            region_name=region_name,
            revenue_rub=round(revenue, -3),
            employees=employees,
            is_client=self.rng.random() < 0.55,
            group_id=f"GRP-{self.rng.randint(1, 10**6):06d}",
        )
        self.companies.append(company)
        self.by_industry.setdefault(industry_id, []).append(company)
        return company

    # ── генерация ──
    def generate(self) -> None:
        industries = [i for i in self.tax.industries if i != UNKNOWN]
        n_regular_targets = N_TARGETS - len(self.demo.companies)
        n_pool = self.n_companies - N_TARGETS
        for _ in range(n_pool):
            revenue = min(math.exp(self.rng.gauss(math.log(6e8), 1.6)), TARGET_REVENUE * 0.95)
            self._new_company(self.rng.choice(industries), max(revenue, 5e6))
        targets = self._make_targets(n_regular_targets)
        for company in targets:
            demo = next((d for d in self.demo.companies if d.company_id == company.company_id), None)
            self._make_payments(company, demo)
        self._add_edge_cases(targets)

    def _make_targets(self, n_regular: int) -> list[Company]:
        targets: list[Company] = []
        for d in self.demo.companies:
            industry_id = self.tax.match_okved(d.okved)
            company = self._new_company(industry_id, d.revenue_rub, cid=d.company_id, name=d.name)
            company.okved, company.region_code, company.region_name = d.okved, d.region_code, d.region_name
            company.is_client = True
            company.products = {code: amount for code, amount in d.products.items()}
            company.ved = [(DEMO_COUNTRY_RAW.get(v.country, v.country), v.direction) for v in d.ved]
            targets.append(company)
        demo_groups = {"wholesale": 0, "construction": 0, "auto": 0, "other": 0}
        for c in targets:
            demo_groups[_group_of(c.industry_id)] += 1
        plan: list[str] = []
        for group, total in GROUP_COUNTS.items():
            pool = {"wholesale": WHOLESALE, "construction": CONSTRUCTION, "auto": AUTO, "other": OTHER}[group]
            plan += [self.rng.choice(pool) for _ in range(total - demo_groups[group])]
        assert len(plan) == n_regular, (len(plan), n_regular)
        regular = [
            self._new_company(ind, math.exp(self.rng.uniform(math.log(1.6e10), math.log(1.2e11))))
            for ind in plan
        ]
        n_total = len(targets) + len(regular)
        # точные доли продуктов, клиентов и ВЭД среди целевых
        n_clients = round(CLIENT_SHARE_TARGETS * n_total) - len(targets)
        n_credit = round(CREDIT_SHARE * n_total) - sum("credit" in c.products for c in targets)
        n_leasing = round(LEASING_SHARE * n_total) - sum("leasing" in c.products for c in targets)
        n_ved = round(VED_SHARE * n_total) - sum(bool(c.ved) for c in targets)
        for idx, company in enumerate(self._shuffled(regular)):
            company.is_client = idx < n_clients
        for idx, company in enumerate(self._shuffled(regular)):
            if idx < n_credit:
                company.products["credit"] = round(company.revenue_rub * self.rng.uniform(0.03, 0.15), -6)
        for idx, company in enumerate(self._shuffled(regular)):
            if idx < n_leasing:
                company.products["leasing"] = round(company.revenue_rub * self.rng.uniform(0.005, 0.03), -6)
        for company in regular:
            for code in OTHER_PRODUCTS:
                if self.rng.random() < 0.25:
                    company.products[code] = None
        names = [raw for raw, _ in VED_COUNTRIES]
        weights = [w for _, w in VED_COUNTRIES]
        for idx, company in enumerate(self._shuffled(regular)):
            if idx < n_ved:
                k = 1 if self.rng.random() < 0.7 else 2
                countries = list(dict.fromkeys(self.rng.choices(names, weights=weights, k=k)))
                company.ved = [(c, "import" if self.rng.random() < 0.8 else "export") for c in countries]
        return targets + regular

    def _shuffled(self, items: list[Company]) -> list[Company]:
        copy = list(items)
        self.rng.shuffle(copy)
        return copy

    def _mix(self, company: Company, demo: DemoCompany | None, direction: str) -> dict[str, float]:
        if demo is not None:
            mix = demo.suppliers_mix if direction == "out" else demo.buyers_mix
            noisy = {k: max(0.0, v + self.rng.uniform(-0.004, 0.004)) for k, v in mix.items()}
            total = sum(noisy.values())
            return {k: v / total for k, v in noisy.items()}
        typical = (
            self.tax.typical_suppliers(company.industry_id)
            if direction == "out"
            else self.tax.typical_buyers(company.industry_id)
        )
        if not typical:  # розница: покупатели — физлица, в платежах их нет; берём немного B2B
            typical = {"business_services": 0.5, "public_social": 0.5}
        keys = list(typical)
        shares = dirichlet(self.rng, [DIRICHLET_ALPHA * len(keys) * typical[k] for k in keys])
        unknown = self.rng.uniform(0.05, 0.2)
        mix = {k: s * (1 - unknown) for k, s in zip(keys, shares, strict=True)}
        mix[UNKNOWN] = unknown
        return mix

    def _counterparty(self, industry_id: str, exclude: set[str]) -> Counterparty:
        pool = [c for c in self.by_industry.get(industry_id, []) if c.company_id not in exclude]
        if industry_id != UNKNOWN and pool and self.rng.random() >= OUT_OF_TABLE_SHARE:
            c = self.rng.choice(pool)
            return Counterparty(c.company_id, c.inn, c.name, "", c.industry_id)
        self._ext_seq += 1
        cid = f"EXT-{self._ext_seq:06d}"
        if industry_id == UNKNOWN:
            if self.rng.random() < 0.3:
                name = f"ИП {self.rng.choice(SURNAMES)} {self.rng.choice('АБВГДЕИКМНОП')}. {self.rng.choice('АБВГДЕИКМНОП')}."
                cp = Counterparty(cid, inn12(self.rng), name, "", UNKNOWN)
            else:
                cp = Counterparty(cid, inn10(self.rng), self._name(None, neutral=True), "", UNKNOWN)
        else:
            name = self._name(industry_id)
            resolvable = match_name_industry(name, self.tax) == industry_id
            okved = self._okved_for(industry_id) if not resolvable or self.rng.random() < 0.4 else ""
            cp = Counterparty(cid, inn10(self.rng), name, okved, industry_id)
        self.external[cid] = cp
        return cp

    def _make_payments(self, company: Company, demo: DemoCompany | None) -> None:
        n_total = self.rng.randint(150, 600)
        for direction, volume in (("in", company.revenue_rub), ("out", company.revenue_rub * 0.85)):
            mix = self._mix(company, demo, direction)
            n_dir = n_total // 2
            exclude = {company.company_id}
            for industry_id, share in sorted(mix.items()):
                if share <= 0:
                    continue
                n_cp = max(1, round(n_dir * share))
                weights = [math.exp(self.rng.gauss(0, 1.0)) for _ in range(n_cp)]
                wsum = sum(weights)
                for w in weights:
                    cp = self._counterparty(industry_id, exclude)
                    exclude.add(cp.counterparty_id)
                    amount = round(volume * share * w / wsum, 2)
                    tx = max(1, int(amount / self.rng.uniform(2e6, 2e7)))
                    self.payments.append((company.company_id, cp, direction, amount, tx))

    def _add_edge_cases(self, targets: list[Company]) -> None:
        """Платёж самому себе и внутри группы — для проверки исключений при сборке."""
        regular = [t for t in targets if not t.company_id.startswith("SYN-DEMO")]
        first = regular[0]
        self_cp = Counterparty(first.company_id, first.inn, first.name, "", first.industry_id)
        self.payments.append((first.company_id, self_cp, "out", 1_000_000.0, 1))
        sister = self._new_company(first.industry_id, 2e9)
        sister.group_id = first.group_id
        sister_cp = Counterparty(sister.company_id, sister.inn, sister.name, "", sister.industry_id)
        self.payments.append((first.company_id, sister_cp, "out", 5_000_000.0, 3))

    # ── запись ──
    def render(self) -> dict[str, str]:
        files: dict[str, str] = {}
        files["companies.csv"] = _csv(
            [
                "company_id",
                "inn",
                "name",
                "okved",
                "okved_secondary",
                "region_code",
                "region_name",
                "revenue_rub",
                "employees",
                "is_client",
                "group_id",
            ],
            [
                [
                    c.company_id,
                    c.inn,
                    c.name,
                    c.okved,
                    "",
                    c.region_code,
                    c.region_name,
                    f"{c.revenue_rub:.0f}",
                    c.employees,
                    "true" if c.is_client else "false",
                    c.group_id,
                ]
                for c in self.companies
            ],
        )
        files["products.csv"] = _csv(
            ["company_id", "product_code", "amount_rub"],
            [
                [c.company_id, code, "" if amount is None else f"{amount:.0f}"]
                for c in self.companies
                for code, amount in sorted(c.products.items())
            ],
        )
        files["ved.csv"] = _csv(
            ["company_id", "country_raw", "direction", "amount_rub"],
            [[c.company_id, raw, direction, ""] for c in self.companies for raw, direction in c.ved],
        )
        files["payments.csv"] = _csv(
            [
                "company_id",
                "counterparty_id",
                "counterparty_inn",
                "counterparty_name",
                "counterparty_okved",
                "direction",
                "amount_rub",
                "tx_count",
                "period",
            ],
            [
                [cid, cp.counterparty_id, cp.inn, cp.name, cp.okved, direction, f"{amount:.2f}", tx, PERIOD]
                for cid, cp, direction, amount, tx in self.payments
            ],
        )
        return files


def _group_of(industry_id: str) -> str:
    if industry_id in WHOLESALE or industry_id.startswith("wholesale"):
        return "wholesale"
    if industry_id in CONSTRUCTION:
        return "construction"
    if industry_id in AUTO:
        return "auto"
    return "other"


def _csv(header: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def generate_synthetic(
    taxonomy: Taxonomy, demo: DemoConfig, out_dir: Path, *, seed: int = 42, companies: int = 3000
) -> dict[str, int]:
    gen = SyntheticGenerator(taxonomy, demo, seed=seed, companies=companies)
    gen.generate()
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name, content in gen.render().items():
        data = content.encode("utf-8")
        (out_dir / name).write_bytes(data)
        sizes[name] = len(data)
    return sizes
