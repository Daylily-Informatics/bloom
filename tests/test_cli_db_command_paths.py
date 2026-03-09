"""Additional coverage for Bloom DB CLI command wiring."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from bloom_lims.cli import cli as root_cli

db_commands = importlib.import_module("bloom_lims.cli.db")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_tapdb_namespace_config_path_prefers_explicit_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "tapdb-config.yaml"
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {"TAPDB_CONFIG_PATH": str(explicit)})
    assert db_commands._tapdb_namespace_config_path("bloom", "bloom") == explicit


def test_tapdb_namespace_config_path_defaults_under_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {})
    monkeypatch.setattr(db_commands.Path, "home", lambda: tmp_path)

    path = db_commands._tapdb_namespace_config_path("bloom", "bloom")
    assert path == tmp_path / ".config" / "tapdb" / "bloom" / "bloom" / "tapdb-config.yaml"


def test_run_tapdb_raises_for_nonzero_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_commands, "_tapdb_base_cmd", lambda: ["tapdb"])
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {})
    monkeypatch.setattr(
        db_commands.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )

    with pytest.raises(SystemExit) as exc:
        db_commands._run_tapdb(["db", "setup"], check=True)

    assert exc.value.code == 7


def test_run_tapdb_returns_nonzero_when_check_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_commands, "_tapdb_base_cmd", lambda: ["tapdb"])
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {})
    monkeypatch.setattr(
        db_commands.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3),
    )

    assert db_commands._run_tapdb(["db", "setup"], check=False) == 3


def test_db_auth_setup_includes_optional_arguments(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append(args) or 0,
    )

    result = runner.invoke(
        root_cli,
        [
            "db",
            "auth-setup",
            "--pool-name",
            "pool-a",
            "--region",
            "us-east-2",
            "--port",
            "9123",
            "--domain-prefix",
            "bloom-dev",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        [
            "cognito",
            "setup",
            "dev",
            "--client-name",
            "bloom",
            "--callback-url",
            "https://localhost:9123/auth/callback",
            "--logout-url",
            "https://localhost:9123/",
            "--region",
            "us-east-2",
            "--pool-name",
            "pool-a",
            "--domain-prefix",
            "bloom-dev",
        ]
    ]


def test_db_start_uses_local_pg_for_dev(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(db_commands, "_local_pg_port", lambda _env: "7000")
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "start"])
    assert result.exit_code == 0
    assert calls == [["pg", "start-local", "dev", "--port", "7000"]]


def test_db_start_uses_default_pg_for_non_local_env(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "prod")
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "start"])
    assert result.exit_code == 0
    assert calls == [["pg", "start"]]


def test_db_status_runs_info_and_schema_status(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "test")
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "status"])
    assert result.exit_code == 0
    assert calls == [["info"], ["db", "schema", "status", "test"]]


def test_db_migrate_ignores_non_head_revision(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(db_commands, "_ensure_schema_available_for_bloom_root", lambda: None)
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "migrate", "--revision", "abc123"])
    assert result.exit_code == 0
    assert "ignored" in result.output.lower()
    assert calls == [["db", "schema", "migrate", "dev"]]


def test_db_seed_calls_tapdb_and_bloom_seeders(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tapdb_seed: list[tuple[str, bool, bool]] = []
    bloom_seed_called = {"value": False}
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_seed_tapdb_templates",
        lambda env_name, include_workflow, overwrite: tapdb_seed.append(
            (env_name, include_workflow, overwrite)
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_seed_bloom_templates",
        lambda: bloom_seed_called.__setitem__("value", True),
    )

    result = runner.invoke(root_cli, ["db", "seed"])
    assert result.exit_code == 0
    assert tapdb_seed == [("dev", False, False)]
    assert bloom_seed_called["value"] is True


def test_db_shell_aurora_connects_via_tapdb(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "get_tapdb_db_config",
        lambda env_name: {
            "host": "db.example",
            "port": "5432",
            "database": "bloom_dev",
            "engine_type": "aurora",
        },
    )
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "shell"])
    assert result.exit_code == 0
    assert calls == [["aurora", "connect", "dev"]]


def test_db_shell_non_aurora_shows_info(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "get_tapdb_db_config",
        lambda env_name: {
            "host": "localhost",
            "port": "5566",
            "database": "bloom_dev",
            "engine_type": "local",
        },
    )
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: calls.append(args) or 0)

    result = runner.invoke(root_cli, ["db", "shell"])
    assert result.exit_code == 0
    assert calls == [["info"]]


def test_db_reset_aborts_when_confirmation_declined(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(db_commands.click, "confirm", lambda _prompt: False)
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda _args: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = runner.invoke(root_cli, ["db", "reset"])
    assert result.exit_code == 0
    assert "Aborted" in result.output


def test_db_reset_yes_runs_force_reset_and_seed(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tapdb_calls: list[list[str]] = []
    seeded: list[tuple[str, bool, bool]] = []
    bloom_seed = {"value": False}

    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(db_commands, "_ensure_schema_available_for_bloom_root", lambda: None)
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda args: tapdb_calls.append(args) or 0)
    monkeypatch.setattr(
        db_commands,
        "_seed_tapdb_templates",
        lambda env_name, include_workflow, overwrite: seeded.append(
            (env_name, include_workflow, overwrite)
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_seed_bloom_templates",
        lambda: bloom_seed.__setitem__("value", True),
    )

    result = runner.invoke(root_cli, ["db", "reset", "--yes"])
    assert result.exit_code == 0
    assert tapdb_calls == [
        ["db", "schema", "reset", "dev", "--force"],
        ["db", "setup", "dev", "--force"],
    ]
    assert seeded == [("dev", False, True)]
    assert bloom_seed["value"] is True
