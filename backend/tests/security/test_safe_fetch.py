from __future__ import annotations

import httpx
import pytest

from alfa_insight.errors import BlockedUrl, UnsupportedContent
from alfa_insight.net.safe_fetch import ip_allowed, safe_fetch, validate_url


def resolver(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, ["93.184.216.34"])

    return resolve


def ok_transport(
    body: bytes = b"<html><p>hi</p></html>", ctype: str = "text/html; charset=utf-8"
) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers={"content-type": ctype}))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://localhost/",
        "http://printer.local/",
        "http://metadata.google.internal/",
        "ftp://example.com/",
        "http://example.com:8080/",
        "http://user:pass@example.com/",
    ],
)
async def test_safe_fetch_blocks_private(url: str) -> None:
    with pytest.raises(BlockedUrl):
        await safe_fetch(url, resolver=resolver({}), transport=ok_transport())


async def test_domain_resolving_to_private_ip() -> None:
    with pytest.raises(BlockedUrl):
        await safe_fetch(
            "https://evil.example/",
            resolver=resolver({"evil.example": ["10.1.2.3"]}),
            transport=ok_transport(),
        )
    with pytest.raises(BlockedUrl):  # хотя бы один адрес приватный
        await safe_fetch(
            "https://mixed.example/",
            resolver=resolver({"mixed.example": ["93.184.216.34", "192.168.0.5"]}),
            transport=ok_transport(),
        )


async def test_safe_fetch_redirect_validation() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(BlockedUrl):
        await safe_fetch(
            "https://news.example/a", resolver=resolver({}), transport=httpx.MockTransport(handler)
        )


async def test_redirect_chain_and_pinning() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    res = await safe_fetch(
        "https://news.example/a", resolver=resolver({}), transport=httpx.MockTransport(handler), pin_ip=True
    )
    assert res.url_final == "https://news.example/b" and res.status == 200
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "news.example"
    assert seen[0].extensions["sni_hostname"] == "news.example"


async def test_too_many_redirects() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={"location": "/loop"}))
    with pytest.raises(BlockedUrl, match="перенаправлений"):
        await safe_fetch("https://news.example/", resolver=resolver({}), transport=transport)


async def test_safe_fetch_limits() -> None:
    with pytest.raises(UnsupportedContent, match="большая"):
        await safe_fetch(
            "https://news.example/",
            resolver=resolver({}),
            transport=ok_transport(b"x" * 5000),
            max_bytes=1000,
        )
    with pytest.raises(UnsupportedContent, match="тип"):
        await safe_fetch(
            "https://news.example/", resolver=resolver({}), transport=ok_transport(b"%PDF", "application/pdf")
        )
    res = await safe_fetch(
        "https://news.example/",
        resolver=resolver({}),
        transport=ok_transport("Привет".encode("cp1251"), "text/plain; charset=windows-1251"),
    )
    assert res.text == "Привет"


def test_ip_rules() -> None:
    assert ip_allowed("93.184.216.34")
    for bad in ("100.64.1.1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "0.0.0.0", "224.0.0.1"):
        assert not ip_allowed(bad), bad
    assert validate_url("https://www.cbr.ru/press/") == ("www.cbr.ru", "https", 443)
    with pytest.raises(BlockedUrl):
        validate_url("https://x.ru/" + "a" * 2100)
