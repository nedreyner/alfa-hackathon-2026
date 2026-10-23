"""`alfa llm probe`: какие возможности реально есть у моделей шлюза (docs/04-llm.md §3)."""

from __future__ import annotations

import base64
import difflib
import json
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Any

from alfa_insight.llm.client import GatewayClient, GatewayError
from alfa_insight.llm.types import ModelConfig, ModelsConfig

TESTS = ("basic", "tools", "json_schema", "json_object", "vision")

# Цифры 5×7 для тестовой картинки
_GLYPHS = {
    "4": ["10010", "10010", "10010", "11111", "00010", "00010", "00010"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
}


def png_with_number(text: str = "42", scale: int = 4) -> bytes:
    """PNG 64×32 с напечатанным числом (без внешних библиотек)."""
    w, h = 64, 32
    pixels = [[255] * w for _ in range(h)]
    x0 = (w - len(text) * 6 * scale // 2) // 2
    y0 = (h - 7 * scale // 2) // 2
    s = scale // 2
    for i, ch in enumerate(text):
        for gy, row in enumerate(_GLYPHS[ch]):
            for gx, bit in enumerate(row):
                if bit == "1":
                    for dy in range(s):
                        for dx in range(s):
                            pixels[y0 + gy * s + dy][x0 + (i * 6 + gx) * s + dx] = 0
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _msg(resp: dict[str, Any]) -> dict[str, Any]:
    return ((resp.get("choices") or [{}])[0]).get("message") or {}


async def _call(
    client: GatewayClient, model: ModelConfig, payload: dict[str, Any], token_param: str
) -> tuple[dict[str, Any], str, float]:
    """Вызов с подбором имени параметра лимита: при 400 про max_tokens пробуем другое имя."""
    limit = payload.pop("_limit", 64)
    body = {**payload, token_param: limit, "extra_body": {"reasoning": {"enabled": False}}}
    started = time.monotonic()
    try:
        resp, _ = await client.chat(model.id, body, 30)
    except GatewayError as err:
        other = "max_completion_tokens" if token_param == "max_tokens" else "max_tokens"
        if err.status == 400 and ("max_tokens" in str(err) or "max_completion_tokens" in str(err)):
            body = {k: v for k, v in body.items() if k != token_param} | {other: body[token_param]}
            resp, _ = await client.chat(model.id, body, 30)
            token_param = other
        else:
            raise
    return resp, token_param, (time.monotonic() - started) * 1000


async def probe_model(client: GatewayClient, model: ModelConfig, token_param: str) -> dict[str, Any]:
    result: dict[str, Any] = {"id": model.id, "tests": {}, "capabilities": {}, "token_param": token_param}
    tests = result["tests"]
    cost = 0.0

    async def run(name: str, payload: dict[str, Any], check: Any) -> None:
        nonlocal token_param, cost
        try:
            resp, token_param, latency = await _call(client, model, payload, token_param)
            usage = resp.get("usage") or {}
            cost += float(usage.get("cost") or 0.0)
            ok, note = check(resp)
            tests[name] = {"ok": bool(ok), "latency_ms": round(latency), "note": note, "usage": bool(usage)}
        except GatewayError as err:
            tests[name] = {"ok": False, "status": err.status, "note": str(err)[:200]}
        except Exception as err:
            tests[name] = {"ok": False, "note": f"{type(err).__name__}: {err}"[:200]}

    user = [{"role": "user", "content": "Ответь одним словом: ок"}]

    def check_basic(r: dict[str, Any]) -> tuple[bool, str]:
        details = (r.get("usage") or {}).get("completion_tokens_details") or {}
        result["reasoning_tokens"] = details.get("reasoning_tokens")
        return bool(_msg(r).get("content")), _msg(r).get("content") or ""

    await run("basic", {"messages": user, "_limit": 64}, check_basic)

    tool = {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Текущее время в городе",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }

    def check_tools(r: dict[str, Any]) -> tuple[bool, str]:
        calls = _msg(r).get("tool_calls") or []
        if not calls:
            return False, "нет tool_calls"
        args = json.loads(calls[0]["function"]["arguments"] or "{}")
        return "city" in args, json.dumps(args, ensure_ascii=False)

    await run(
        "tools",
        {
            "messages": [{"role": "user", "content": "Который час в Москве?"}],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": "get_time"}},
            "_limit": 256,
        },
        check_tools,
    )

    def check_json(r: dict[str, Any]) -> tuple[bool, str]:
        text = _msg(r).get("content") or ""
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else None
        return isinstance(data, dict) and "answer" in data, text[:80]

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    q = [{"role": "user", "content": 'Сколько будет 2+2? Верни JSON {"answer": "..."}'}]
    await run(
        "json_schema",
        {
            "messages": q,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
            "_limit": 256,
        },
        check_json,
    )
    await run(
        "json_object", {"messages": q, "response_format": {"type": "json_object"}, "_limit": 256}, check_json
    )

    if model.capabilities.vision:
        image = "data:image/png;base64," + base64.b64encode(png_with_number("42")).decode()
        vision_msg = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Какое число на картинке? Ответь только числом."},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            }
        ]
        await run(
            "vision",
            {"messages": vision_msg, "_limit": 16},
            lambda r: ("42" in (_msg(r).get("content") or ""), _msg(r).get("content")),
        )

    result["token_param"] = token_param
    result["cost_rub"] = round(cost, 6)
    result["capabilities"] = {
        "tools": tests.get("tools", {}).get("ok", False),
        "json_schema": tests.get("json_schema", {}).get("ok", False),
        "json_object": tests.get("json_object", {}).get("ok", False),
        "vision": tests.get("vision", {}).get("ok", False) if model.capabilities.vision else False,
        "usage": tests.get("basic", {}).get("usage", False),
        "reasoning_toggle": tests.get("basic", {}).get("ok", False)
        and (result.get("reasoning_tokens") or 0) <= 5,
    }
    return result


async def run_probe(config: ModelsConfig, client: GatewayClient) -> dict[str, Any]:
    listing: dict[str, Any] = {}
    try:
        listing = {str(k): v for k, v in (await client.list_models()).items()}
    except GatewayError as err:
        listing = {"error": str(err)}
    available = set(listing.get("primary") or []) | set(listing.get("fallback") or [])
    report: dict[str, Any] = {"listing": listing, "models": {}, "mismatches": {}}
    for key, model in config.models.items():
        if available and model.id not in available:
            report["mismatches"][key] = difflib.get_close_matches(model.id, sorted(available), n=3)
            continue
        report["models"][key] = await probe_model(
            client, model, model.token_param or config.gateway.token_param
        )
    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [f"{'модель':10} " + " ".join(f"{t:11}" for t in TESTS) + " token_param            ₽"]
    for key, item in report["models"].items():
        cells = []
        for t in TESTS:
            r = item["tests"].get(t)
            cells.append(f"{'—' if r is None else ('да' if r['ok'] else 'нет'):11}")
        lines.append(f"{key:10} " + " ".join(cells) + f" {item['token_param']:22} {item['cost_rub']:.5f}")
    for key, close in report.get("mismatches", {}).items():
        lines.append(f"{key}: модели нет в /models, похожие: {', '.join(close) or '—'}")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return str(v).lower()
    return str(v)


def render_models_block(config: ModelsConfig, report: dict[str, Any]) -> str:
    lines = ["models:"]
    for key, m in config.models.items():
        probed = report["models"].get(key, {})
        if not probed.get("tests", {}).get("basic", {}).get("ok"):
            probed = {}  # модель не ответила — оставляем прежние значения
        caps = {**m.capabilities.model_dump(), **probed.get("capabilities", {})}
        token = probed.get("token_param") or m.token_param
        price = m.price_rub_per_1m
        head = (
            f'  {key}: {{id: "{m.id}", family: {m.family}, context_tokens: {m.context_tokens}, '
            f"price_rub_per_1m: {{input: {_fmt(price.input)}, output: {_fmt(price.output)}}},"
        )
        tail = "    capabilities: {" + ", ".join(f"{k}: {_fmt(v)}" for k, v in caps.items()) + "}"
        tail += f", token_param: {token}}}" if token else "}"
        lines += [head, tail]
    return "\n".join(lines) + "\n"


def write_config(path: Path, config: ModelsConfig, report: dict[str, Any]) -> None:
    """Перенести capabilities и token_param в models.yaml; остальные разделы файла не трогаются."""
    text = path.read_text(encoding="utf-8")
    start = text.index("\nmodels:\n") + 1
    end = text.index("\ntasks:", start) + 1
    path.write_text(text[:start] + render_models_block(config, report) + text[end:], encoding="utf-8")
