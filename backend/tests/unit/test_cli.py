from typer.testing import CliRunner

from alfa_insight.cli import GROUPS, app

runner = CliRunner()


def test_help_lists_all_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in [*GROUPS, "db", "data", "llm", "ingest", "seed", "init", "worker", "precompute"]:
        assert name in result.output


def test_stub_returns_exit_code_2() -> None:
    result = runner.invoke(app, ["worker"])
    assert result.exit_code == 2
