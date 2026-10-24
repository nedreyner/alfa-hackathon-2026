from __future__ import annotations

from fastapi.testclient import TestClient

from alfa_insight.appctx import AppContext


def login(client: TestClient, company: str = "SYN-DEMO-01", role: str = "cfo") -> None:
    assert client.post("/api/session", json={"company_id": company, "role": role}).status_code == 200


def test_profile_and_counterparties(client: TestClient) -> None:
    assert client.get("/api/me/profile").status_code == 401
    login(client)
    prof = client.get("/api/me/profile").json()
    assert prof["profile"]["company_id"] == "SYN-DEMO-01" and prof["overrides"] == []
    cp = client.get(
        "/api/me/counterparties", params={"direction": "suppliers", "industry_id": "metallurgy", "limit": 3}
    ).json()
    assert (
        cp["direction"] == "suppliers" and cp["basis"] in ("blended", "payments") and 0 < cp["coverage"] <= 1
    )
    assert (
        cp["items"] and len(cp["items"]) <= 3 and all(i["industry_id"] == "metallurgy" for i in cp["items"])
    )
    assert any(m["industry_id"] == "metallurgy" for m in cp["mix"])
    assert client.get("/api/me/counterparties", params={"industry_id": "steel"}).status_code == 400


def test_overrides_rerank(client: TestClient, api_ctx: AppContext, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ranked: list[str] = []
    original = api_ctx.ranking.rank_company

    def spy(company_id: str, **kw):  # type: ignore[no-untyped-def]
        ranked.append(company_id)
        return original(company_id, **kw)

    monkeypatch.setattr(api_ctx.ranking, "rank_company", spy)
    login(client, "SYN-DEMO-02")
    before = client.get("/api/me/profile").json()["profile"]
    r = client.put(
        "/api/me/profile/overrides",
        json={"industry_id": "wholesale_fuel", "ved": [{"country_iso2": "cn", "direction": "import"}],
              "products": {"leasing": False, "fx": True}, "notes": "Возим топливо из Китая"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    after = r.json()
    assert (
        after["profile"]["industry_id"] == "wholesale_fuel"
        and after["profile"]["ved"][0]["country_iso2"] == "CN"
    )
    assert after["profile"]["profile_version"] != before["profile_version"]
    assert {o["field"] for o in after["overrides"]} == {"industry_id", "ved", "products", "notes"}
    assert (
        after["profile"]["products"]["fx"]["has"] is True
        and after["profile"]["products"]["leasing"]["has"] is False
    )
    assert ranked == ["SYN-DEMO-02"]  # правка пересчитывает ранжирование компании

    r = client.put("/api/me/profile/overrides", json={"reset": ["industry_id", "ved", "products", "notes"]})
    assert r.json()["overrides"] == [] and r.json()["profile"]["industry_id"] == before["industry_id"]
    assert client.put("/api/me/profile/overrides", json={"industry_id": "space_mining"}).status_code == 400
    assert (
        client.put(
            "/api/me/profile/overrides", json={"ved": [{"country_iso2": "ZZ", "direction": "import"}]}
        ).status_code
        == 400
    )
