"""Логи structlog: JSON в проде, консоль в разработке. Контекст — через contextvars."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO", *, json: bool = False) -> None:
    global _configured
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    renderer: Any = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(component: str) -> Any:
    return structlog.get_logger().bind(component=component)


def bind_context(**fields: Any) -> None:
    structlog.contextvars.bind_contextvars(**{k: v for k, v in fields.items() if v is not None})


def clear_context(*keys: str) -> None:
    if keys:
        structlog.contextvars.unbind_contextvars(*keys)
    else:
        structlog.contextvars.clear_contextvars()
