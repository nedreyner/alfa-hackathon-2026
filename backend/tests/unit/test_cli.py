from typer.testing import CliRunner

from alfa_insight.cli import GROUPS, app

runner = CliRunner()


def test_help_lists_all_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in [
        *GROUPS,
        "db",
        "data",
        "llm",
        "ingest",
        "seed",
        "pipeline",
        "macro",
        "init",
        "worker",
        "precompute",
    ]:
        assert name in result.output


def test_stub_returns_exit_code_2() -> None:
    result = runner.invoke(app, ["eval"])  # ещё не реализована (T6.2)
    assert result.exit_code == 2


def test_init_is_idempotent() -> None:
    """`alfa init` во временном DATA_DIR (fake LLM): все шаги, повторный запуск тоже проходит."""
    for _ in range(2):
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0, result.output
        assert "8/8 ранжирование" in result.output and "init: готово" in result.output


def test_default_settings_are_isolated_from_repo_data() -> None:
    """CLI в тестах (get_settings) не должен видеть рабочую базу data/runtime репозитория."""
    from pathlib import Path

    from alfa_insight.settings import get_settings

    get_settings.cache_clear()
    repo_data = Path(__file__).resolve().parents[3] / "data"
    assert get_settings().data_dir != repo_data and get_settings().llm_mode == "fake"
