"""Общий контейнер зависимостей для api, worker и cli. Тяжёлые части создаются при первом обращении."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from alfa_insight.db.sqlite import SqliteDB, open_db
from alfa_insight.ingest.sources import SourcesConfig, load_sources
from alfa_insight.reference.taxonomy import Taxonomy, load_taxonomy
from alfa_insight.settings import Settings, get_settings
from alfa_insight.store.kv import KVStore

if TYPE_CHECKING:
    from alfa_insight.config_models import DemoConfig
    from alfa_insight.data.counterparties import CounterpartyReader
    from alfa_insight.data.profiles import ProfileStore
    from alfa_insight.db.duck import DuckReader
    from alfa_insight.llm.prompts import PromptLoader
    from alfa_insight.llm.router import LLMRouter
    from alfa_insight.ranking.models import RankingConfig
    from alfa_insight.ranking.service import RankingService


@dataclass
class AppContext:
    settings: Settings
    db: SqliteDB
    taxonomy: Taxonomy
    sources: SourcesConfig
    kv: KVStore
    _lazy: dict[str, Any] = field(default_factory=dict)

    def _get(self, name: str, factory: Any) -> Any:
        if name not in self._lazy:
            self._lazy[name] = factory()
        return self._lazy[name]

    @property
    def router(self) -> LLMRouter:
        from alfa_insight.llm import build_router

        return self._get("router", lambda: build_router(self.settings, self.db))  # type: ignore[no-any-return]

    def set_router(self, router: LLMRouter) -> None:
        self._lazy["router"] = router

    @property
    def prompts(self) -> PromptLoader:
        from alfa_insight.llm.prompts import PromptLoader

        return self._get(  # type: ignore[no-any-return]
            "prompts", lambda: PromptLoader(version_suffix={"tagging": f"tx{self.taxonomy.version}"})
        )

    @property
    def demo(self) -> DemoConfig:
        from alfa_insight.config_models import DemoConfig, load_yaml

        return self._get("demo", lambda: load_yaml(self.settings.config_path / "demo.yaml", DemoConfig))  # type: ignore[no-any-return]

    @property
    def duck(self) -> DuckReader:
        from alfa_insight.db.duck import DuckReader

        return self._get("duck", lambda: DuckReader(self.settings.duckdb_path))  # type: ignore[no-any-return]

    @property
    def profiles(self) -> ProfileStore:
        from alfa_insight.data.profiles import ProfileStore
        from alfa_insight.store.profiles import ProfileOverridesRepo

        return self._get(  # type: ignore[no-any-return]
            "profiles",
            lambda: ProfileStore(self.duck, ProfileOverridesRepo(self.db), self.taxonomy, self.demo.ids()),
        )

    @property
    def ranking_config(self) -> RankingConfig:
        from alfa_insight.config_models import load_yaml
        from alfa_insight.ranking.models import RankingConfig

        return self._get(
            "ranking_config", lambda: load_yaml(self.settings.config_path / "ranking.yaml", RankingConfig)
        )  # type: ignore[no-any-return]

    @property
    def ranking(self) -> RankingService:
        from alfa_insight.ranking.service import RankingService

        return self._get(  # type: ignore[no-any-return]
            "ranking", lambda: RankingService(self.db, self.profiles, self.ranking_config, self.taxonomy)
        )

    @property
    def counterparties(self) -> CounterpartyReader:
        from alfa_insight.data.counterparties import CounterpartyReader

        return self._get("counterparties", lambda: CounterpartyReader(self.duck, self.taxonomy))  # type: ignore[no-any-return]


def build_context(settings: Settings | None = None) -> AppContext:
    s = settings or get_settings()
    db = open_db(s.sqlite_path)
    return AppContext(
        settings=s,
        db=db,
        taxonomy=load_taxonomy(s.reference_dir),
        sources=load_sources(s.config_path),
        kv=KVStore(db),
    )
