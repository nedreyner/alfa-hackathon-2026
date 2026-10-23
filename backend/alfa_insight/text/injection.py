"""Детектор промпт-инъекций по шаблонам `injection_patterns.yaml` (docs/11-security.md §4)."""

from __future__ import annotations

import re

from alfa_insight.reference.models import InjectionPatternsFile
from alfa_insight.text.normalize import count_invisible

INVISIBLE_FLAG = "invisible_chars"


class InjectionDetector:
    def __init__(self, patterns: InjectionPatternsFile):
        self.max_invisible = patterns.max_invisible_chars
        self._patterns = [(p.id, re.compile(p.regex, re.I | re.U)) for p in patterns.patterns]

    def detect(self, *texts: str | None) -> list[str]:
        flags: list[str] = []
        for text in texts:
            if not text:
                continue
            for pid, rx in self._patterns:
                if pid not in flags and rx.search(text):
                    flags.append(pid)
            if INVISIBLE_FLAG not in flags and count_invisible(text) > self.max_invisible:
                flags.append(INVISIBLE_FLAG)
        return flags
