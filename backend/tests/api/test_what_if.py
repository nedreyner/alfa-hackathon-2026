from __future__ import annotations

import pytest

from alfa_insight.data.models import CompanyProfile
from alfa_insight.services.what_if import fx_scenario, rate_scenario


def _profile(app, cid: str) -> CompanyProfile:  # type: ignore[no-untyped-def]
    return app.profiles.get(cid)


def test_rate_scenario_arithmetic(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    p = _profile(seeded_ctx, "SYN-DEMO-02")  # кредит 9 млрд + лизинг 0.6 млрд, выручка 32 млрд
    r = rate_scenario(p, 14.0, -2.0)
    assert r.debt_rub == pytest.approx(9.6e9) and r.delta_rub_year == pytest.approx(-192e6)
    assert r.key_rate_new == 12.0 and r.share_of_revenue == pytest.approx(0.006)
    assert "снизятся" in r.text and "192 млн ₽" in r.text and r.level == "high"
    assert "Сдвиньте" in rate_scenario(p, 14.0, 0.0).text


def test_fx_scenario_direction(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    imp = fx_scenario(_profile(seeded_ctx, "SYN-DEMO-01"), "CNY", 12.0, 10.0)
    assert imp.direction == "import" and imp.rate_new == pytest.approx(13.2) and "дороже" in imp.text
    assert imp.delta_rub_per_billion == pytest.approx(1e8) and imp.level == "high"
    exp = fx_scenario(_profile(seeded_ctx, "SYN-DEMO-04"), "USD", 80.0, -5.0)
    assert exp.direction == "export" and "меньше" in exp.text
