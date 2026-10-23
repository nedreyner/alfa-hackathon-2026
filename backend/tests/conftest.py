"""Общие фикстуры тестов. LLM всегда работает в режиме fake — к живому шлюзу тесты не ходят."""

from __future__ import annotations

import os

os.environ["LLM_MODE"] = "fake"
