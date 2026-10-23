"""Шаблоны промптов Jinja2 с версиями (docs/04-llm.md §10) и санитизация недоверенного текста."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

from alfa_insight.errors import ConfigError
from alfa_insight.llm.types import Message

DEFAULT_UNTRUSTED_LIMIT = 12_000
# Управляющие (кроме \t \n \r), невидимые и символы-теги Unicode
_INVISIBLE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\U000e0000-\U000e007f]"
)
_CLOSE_TAG = re.compile(r"</\s*untrusted", re.I)


def count_invisible(text: str) -> int:
    return len(_INVISIBLE.findall(text))


def sanitize_untrusted(text: Any, limit: int = DEFAULT_UNTRUSTED_LIMIT) -> str:
    """Удалить невидимые символы, экранировать закрывающий тег обёртки, обрезать до лимита."""
    value = "" if text is None else str(text)
    value = _INVISIBLE.sub("", value)
    value = _CLOSE_TAG.sub(r"<\\/untrusted", value)
    if len(value) > limit:
        value = value[:limit].rstrip() + " […]"
    return value


class PromptSpec(BaseModel):
    version: str
    system: str
    user: str


@dataclass
class RenderedPrompt:
    name: str
    version: str
    messages: list[Message]


def default_prompts_dir() -> Path:
    return Path(str(resources.files("alfa_insight").joinpath("prompts")))


class PromptLoader:
    def __init__(self, directory: Path | None = None, *, version_suffix: dict[str, str] | None = None):
        self.dir = directory or default_prompts_dir()
        raw = yaml.safe_load((self.dir / "registry.yaml").read_text(encoding="utf-8")) or {}
        self.registry = {name: PromptSpec.model_validate(spec) for name, spec in raw.items()}
        self.version_suffix = version_suffix or {}
        self.env = Environment(
            loader=FileSystemLoader(str(self.dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )
        self.env.filters["sanitize_untrusted"] = sanitize_untrusted

    def version(self, name: str) -> str:
        spec = self._spec(name)
        suffix = self.version_suffix.get(name)
        return f"{spec.version}+{suffix}" if suffix else spec.version

    def _spec(self, name: str) -> PromptSpec:
        try:
            return self.registry[name]
        except KeyError as exc:
            raise ConfigError(f"промпт {name!r} не зарегистрирован в registry.yaml") from exc

    def render_part(self, template: str, **ctx: Any) -> str:
        return self.env.get_template(template).render(**ctx).strip()

    def render(self, name: str, **ctx: Any) -> RenderedPrompt:
        spec = self._spec(name)
        system = self.render_part(spec.system, **ctx)
        user = self.render_part(spec.user, **ctx)
        return RenderedPrompt(
            name=name,
            version=self.version(name),
            messages=[Message(role="system", content=system), Message(role="user", content=user)],
        )
