from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from alfa_insight.api.app import create_app
from alfa_insight.api.session import COOKIE
from tests.api.conftest import make_ctx


def test_health_meta_reference(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert (
        meta["llm_mode"] == "fake"
        and meta["budget_mode"] == "normal"
        and {r["id"] for r in meta["roles"]} == {"cfo", "treasurer", "owner"}
    )
    ref = client.get("/api/reference").json()
    assert (
        ref["industries"]
        and ref["products"]
        and ref["products_disclaimer"]
        and ref["version"].startswith("tx")
    )
    assert all(i["id"] != "unknown" for i in ref["industries"])


def test_ready_503_then_200(tmp_path: Path, synthetic_duckdb: Path) -> None:
    empty = make_ctx(tmp_path / "a", None)
    with TestClient(create_app(empty, run_worker=False)) as c:
        r = c.get("/api/ready")
        assert (
            r.status_code == 503
            and r.json()["checks"]["duckdb"] is False
            and r.json()["checks"]["sqlite"] is True
        )
    full = make_ctx(tmp_path / "b", synthetic_duckdb)
    with TestClient(create_app(full, run_worker=False)) as c:
        r = c.get("/api/ready")
        assert r.status_code == 200 and r.json()["ready"] is True and all(r.json()["checks"].values())


def test_session_flow(client: TestClient) -> None:
    assert client.get("/api/session").status_code == 401
    companies = client.get("/api/demo/companies", params={"limit": 3}).json()
    assert companies[0]["is_demo"] and companies[0]["company_id"] == "SYN-DEMO-01" and companies[0]["story"]
    r = client.post("/api/session", json={"company_id": "SYN-DEMO-02", "role": "cfo"})
    assert (
        r.status_code == 200
        and r.json()["company"]["name"] == "ГК «Волга-Строй»"
        and r.json()["role"] == "cfo"
    )
    cookie = r.cookies.get(COOKIE)
    assert (
        cookie
        and "httponly" in r.headers["set-cookie"].lower()
        and "samesite=lax" in r.headers["set-cookie"].lower()
    )
    assert client.get("/api/session").json()["company"]["company_id"] == "SYN-DEMO-02"
    r = client.patch("/api/session", json={"role": "treasurer"})
    assert r.json()["role"] == "treasurer" and client.get("/api/session").json()["role"] == "treasurer"
    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/session").status_code == 401

    # подделанная и испорченная cookie
    client.cookies.set(COOKIE, cookie[:-3] + "abc")
    r = client.get("/api/session")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    client.cookies.set(COOKIE, "garbage")
    assert client.get("/api/session").status_code == 401


def test_errors_format(client: TestClient) -> None:
    r = client.post("/api/session", json={"company_id": "NOPE", "role": "cfo"})
    assert r.status_code == 404 and r.json() == {
        "error": {"code": "not_found", "message": "Компания не найдена", "details": {"company_id": "NOPE"}}
    }
    r = client.post("/api/session", json={"company_id": "SYN-DEMO-01", "role": "ceo"})
    body = r.json()
    assert (
        r.status_code == 422
        and body["error"]["code"] == "validation_error"
        and body["error"]["details"]["errors"][0]["loc"][-1] == "role"
    )
    r = client.get("/api/no-such-route")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/session", json={"company_id": "SYN-DEMO-01", "role": "cfo", "jury_code": "wrong"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_demo_mode_off_and_jury(tmp_path: Path, synthetic_duckdb: Path) -> None:
    ctx = make_ctx(
        tmp_path, synthetic_duckdb, demo_mode=False, jury_code="jury-2026", session_secret="x" * 40
    )
    other = next(c for c in ctx.profiles.company_ids() if not c.startswith("SYN-DEMO"))
    with TestClient(create_app(ctx, run_worker=False)) as c:
        assert c.post("/api/session", json={"company_id": other, "role": "cfo"}).status_code == 403
        assert c.post("/api/session", json={"company_id": "SYN-DEMO-03", "role": "cfo"}).status_code == 200
        r = c.post("/api/session", json={"company_id": other, "role": "owner", "jury_code": "jury-2026"})
        assert r.status_code == 200 and r.json()["jury"] is True


def test_rate_limit_session_by_ip(client: TestClient) -> None:
    codes = [
        client.post("/api/session", json={"company_id": "SYN-DEMO-01", "role": "cfo"}).status_code
        for _ in range(21)
    ]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    r = client.post("/api/session", json={"company_id": "SYN-DEMO-01", "role": "cfo"})
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    other_ip = client.post(
        "/api/session",
        json={"company_id": "SYN-DEMO-01", "role": "cfo"},
        headers={"x-forwarded-for": "10.0.0.9"},
    )
    assert other_ip.status_code == 200


def test_operation_ids(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert {
        "health",
        "ready",
        "meta",
        "list_companies",
        "create_session",
        "get_session",
        "update_session",
        "delete_session",
        "reference",
    } <= ops
