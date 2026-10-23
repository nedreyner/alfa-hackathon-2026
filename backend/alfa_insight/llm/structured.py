"""Структурированный вывод: JSON Schema для моделей, разбор ответа, сообщение для починки (§5)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from alfa_insight.llm.types import STRATEGY_ORDER, ModelCapabilities, Strategy

_DROP_KEYS = {"title", "$defs", "definitions"}


def _resolve(node: Any, defs: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    if isinstance(node, list):
        return [_resolve(x, defs, stack) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        if name in stack:
            raise ValueError(f"рекурсивная схема {name} не поддерживается")
        target = copy.deepcopy(defs[name])
        extra = {k: v for k, v in node.items() if k != "$ref"}
        target.update(extra)
        return _resolve(target, defs, (*stack, name))
    return {k: _resolve(v, defs, stack) for k, v in node.items()}


def _simplify(node: Any) -> Any:
    if isinstance(node, list):
        return [_simplify(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _simplify(v) for k, v in node.items() if k not in _DROP_KEYS}
    if "default" in out and out["default"] is None:
        out.pop("default")
    for key in ("anyOf", "oneOf"):
        variants = out.get(key)
        if isinstance(variants, list):
            non_null = [v for v in variants if v != {"type": "null"}]
            has_null = len(non_null) < len(variants)
            if len(non_null) == 1:
                merged = dict(non_null[0])
                out.pop(key)
                if has_null:
                    t = merged.get("type")
                    if isinstance(t, str):
                        merged["type"] = [t, "null"]
                    elif isinstance(t, list) and "null" not in t:
                        merged["type"] = [*t, "null"]
                    elif "enum" in merged and None not in merged["enum"]:
                        merged["enum"] = [*merged["enum"], None]
                out = {**merged, **out}
    if "const" in out:
        out["enum"] = [out.pop("const")]
    if out.get("type") == "object" or "properties" in out:
        out.setdefault("type", "object")
        out["additionalProperties"] = False
    if out.get("type") == "array" or (isinstance(out.get("type"), list) and "array" in out["type"]):
        if "maxLength" in out:
            out["maxItems"] = out.pop("maxLength")
        if "minLength" in out:
            out["minItems"] = out.pop("minLength")
    return out


def to_llm_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Схема без `$ref`, `$defs`, `title` и `anyOf` с null — так её понимают все провайдеры."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _simplify(_resolve(raw, defs))


def _ts_type(node: dict[str, Any], indent: int) -> str:
    pad = "  " * indent
    if "enum" in node:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in node["enum"])
    t = node.get("type")
    types = t if isinstance(t, list) else [t]
    nullable = "null" in types
    types = [x for x in types if x != "null"]
    base = types[0] if types else None
    if base == "object" or "properties" in node:
        props = node.get("properties", {})
        required = set(node.get("required", []))
        lines = ["{"]
        for name, sub in props.items():
            opt = "" if name in required else "?"
            desc = f"  // {sub['description']}" if sub.get("description") else ""
            lines.append(f"{pad}  {name}{opt}: {_ts_type(sub, indent + 1)};{desc}")
        lines.append(f"{pad}}}")
        text = "\n".join(lines)
    elif base == "array":
        item = node.get("items", {})
        text = f"Array<{_ts_type(item, indent)}>"
        bounds = [
            f"min {node['minItems']}" if "minItems" in node else "",
            f"max {node['maxItems']}" if "maxItems" in node else "",
        ]
        bounds = [b for b in bounds if b]
        if bounds:
            text += f" /* {', '.join(bounds)} */"
    elif base in ("integer", "number"):
        text = "number"
    elif base == "boolean":
        text = "boolean"
    elif base == "string":
        text = "string"
    else:
        text = "any"
    return f"{text} | null" if nullable else text


def schema_to_prompt(schema: dict[str, Any]) -> str:
    """Компактная TypeScript-подобная запись схемы для промпта (json_object, prompt_only)."""
    return _ts_type(schema, 0)


def extract_json_block(text: str | None) -> Any:
    """Первый сбалансированный JSON-объект в тексте (с учётом строк и экранирования)."""
    if not text:
        raise ValueError("пустой ответ")
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = stripped.find("{", start + 1)
    raise ValueError("в ответе нет JSON-объекта")


def choose_strategy(requested: Strategy, caps: ModelCapabilities) -> Strategy:
    available = {
        "tool_call": caps.tools is True,
        "json_schema": caps.json_schema is True,
        "json_object": caps.json_object is True,
        "prompt_only": True,
    }
    if requested != "auto":
        if available.get(requested):
            return requested
        # запрошенная стратегия недоступна — первая доступная ниже по списку
        idx = STRATEGY_ORDER.index(requested)
        for s in STRATEGY_ORDER[idx:]:
            if available[s]:
                return s
        return "prompt_only"
    for s in STRATEGY_ORDER:
        if available[s]:
            return s
    return "prompt_only"


def tool_name(schema: type[BaseModel]) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", schema.__name__).lower()
    return f"submit_{snake}"


def format_validation_errors(exc: Exception, limit: int = 20) -> str:
    if isinstance(exc, ValidationError):
        lines = [f"{'.'.join(str(p) for p in e['loc']) or '<корень>'} — {e['msg']}" for e in exc.errors()]
    else:
        lines = [str(exc)]
    return "\n".join(lines[:limit])


def repair_message(exc: Exception) -> str:
    return (
        "Ответ не прошёл проверку схемы. Ошибки:\n"
        f"{format_validation_errors(exc)}\n"
        "Верни исправленный объект целиком, без пояснений."
    )


def json_instruction(schema: dict[str, Any]) -> str:
    return "Верни только JSON-объект без пояснений и без markdown, строго по схеме:\n" + schema_to_prompt(
        schema
    )
