"""Smoke tests for the CLI scaffold (M0)."""

from typer.testing import CliRunner

from minibook import __version__
from minibook.cli import NOT_IMPLEMENTED_EXIT, app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init-book", "fetch", "run", "backfill"):
        assert cmd in result.stdout


def test_bad_date_rejected() -> None:
    result = runner.invoke(app, ["run", "--date", "2026-13-01"])
    assert result.exit_code != 0


def test_unimplemented_commands_exit_explicitly() -> None:
    result = runner.invoke(app, ["run", "--date", "2026-12-01"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT
