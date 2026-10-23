"""Безопасная загрузка произвольного URL: защита от SSRF (docs/11-security.md §3)."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel

from alfa_insight.errors import BlockedUrl, FetchFailed, UnsupportedContent

DEFAULT_UA = "AlfaInsightBot/0.1 (+https://github.com/nedreyner/alfa-hackathon-2026)"
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
MAX_URL_LEN = 2048
BLOCKED_SUFFIXES = (".local", ".internal", ".localhost")
EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchResult(BaseModel):
    url_final: str
    status: int
    content_type: str
    text: str
    bytes: int
    elapsed_ms: int


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def ip_allowed(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    return not any(ip in net for net in EXTRA_BLOCKED if net.version == ip.version)


def validate_url(url: str) -> tuple[str, str, int]:
    """Правила 1–2: схема, порт, учётные данные, длина, запрещённые имена хостов."""
    if len(url) > MAX_URL_LEN:
        raise BlockedUrl("Слишком длинная ссылка")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise BlockedUrl("Разрешены только ссылки http и https")
    if parts.username or parts.password:
        raise BlockedUrl("Ссылки с логином и паролем запрещены")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedUrl("В ссылке нет адреса сайта")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise BlockedUrl("Некорректный порт") from exc
    if port not in (80, 443):
        raise BlockedUrl("Разрешены только порты 80 и 443")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or host.startswith("metadata."):
        raise BlockedUrl("Адрес внутренней сети запрещён")
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal and not ip_allowed(host.strip("[]")):
        raise BlockedUrl("Адрес внутренней сети запрещён")
    return host, scheme, port


def _proxy_required() -> bool:
    return any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"))


def _decode(data: bytes, response: httpx.Response) -> str:
    charset = response.charset_encoding
    for enc in [c for c in (charset, "utf-8", "cp1251") if c]:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


async def safe_fetch(
    url: str,
    *,
    max_bytes: int = 2_000_000,
    timeout_s: float = 10.0,
    max_redirects: int = 3,
    user_agent: str = DEFAULT_UA,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    pin_ip: bool | None = None,
) -> FetchResult:
    resolve = resolver or system_resolver
    pin = (not _proxy_required()) if pin_ip is None else pin_ip
    started = time.monotonic()
    current = url.strip()
    timeout = httpx.Timeout(timeout_s, connect=min(5.0, timeout_s))
    client_kw: dict[str, Any] = {"timeout": timeout, "follow_redirects": False, "trust_env": not pin}
    if transport is not None:
        client_kw["transport"] = transport
    async with httpx.AsyncClient(**client_kw) as client:
        for _hop in range(max_redirects + 1):
            host, scheme, port = validate_url(current)
            try:
                addrs = await resolve(host, port)
            except OSError as exc:
                if pin:
                    raise FetchFailed(f"Не удалось найти сайт {host}") from exc
                # Через обязательный исходящий прокси DNS разрешает прокси, а локальный резолвер может
                # быть недоступен. Внутренняя сеть контейнера через внешний прокси недостижима; имена и
                # IP-литералы уже проверены validate_url (риск описан в README, раздел «Безопасность»).
                addrs = []
            if (pin and not addrs) or not all(ip_allowed(a) for a in addrs):
                raise BlockedUrl("Адрес внутренней сети запрещён")
            parts = urlsplit(current)
            headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"}
            extensions: dict[str, Any] = {}
            target = current
            if pin:
                ip = addrs[0]
                netloc = f"[{ip}]" if ":" in ip else ip
                if parts.port:
                    netloc += f":{parts.port}"
                target = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
                headers["Host"] = parts.netloc.split("@")[-1]
                if scheme == "https":
                    extensions["sni_hostname"] = host
            request = client.build_request("GET", target, headers=headers, extensions=extensions)
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise FetchFailed(f"Сайт не ответил: {type(exc).__name__}") from exc
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise FetchFailed("Редирект без адреса")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise FetchFailed(
                        f"Сайт вернул ошибку {response.status_code}", {"status": response.status_code}
                    )
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in ALLOWED_TYPES:
                    raise UnsupportedContent(f"Неподдерживаемый тип содержимого: {ctype or 'не указан'}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsupportedContent("Страница слишком большая")
                    chunks.append(chunk)
                data = b"".join(chunks)
                return FetchResult(
                    url_final=current,
                    status=response.status_code,
                    content_type=ctype,
                    text=_decode(data, response),
                    bytes=size,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            finally:
                await response.aclose()
        raise BlockedUrl("Слишком много перенаправлений")
