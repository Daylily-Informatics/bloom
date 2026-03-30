"""Additional coverage for Bloom DB CLI command wiring."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bloom_lims.config import DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT, DEFAULT_BLOOM_WEB_PORT
from bloom_lims.cli import build_app

db_commands = importlib.import_module("bloom_lims.cli.db")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return build_app()


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


def test_update_tapdb_namespace_config_uses_config_update(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "audit.bloom")
    monkeypatch.setattr(db_commands, "_tapdb_support_email", lambda _env: "support@example.com")
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._update_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "config",
                "update",
                "--env",
                "dev",
                "--audit-log-euid-prefix",
                "audit.bloom",
                "--support-email",
                "support@example.com",
            ],
            True,
        )
    ]


def test_ensure_tapdb_namespace_config_initializes_then_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        db_commands,
        "_runtime_env",
        lambda: {
            "TAPDB_CLIENT_ID": "bloom",
            "TAPDB_DATABASE_NAME": "bloom",
            "TAPDB_CONFIG_PATH": "/tmp/.config/tapdb/bloom/bloom-local2/tapdb-config.yaml",
        },
    )
    monkeypatch.setattr(db_commands, "_local_pg_port", lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT))
    monkeypatch.setattr(db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT))
    monkeypatch.setattr(db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "TAG")
    monkeypatch.setattr(db_commands, "_tapdb_support_email", lambda _env: "support@example.com")
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._ensure_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "config",
                "init",
                "--client-id",
                "bloom",
                "--database-name",
                "bloom",
                "--env",
                "dev",
                "--db-port",
                "dev=5566",
                "--ui-port",
                "dev=8912",
            ],
            True,
        ),
        (
            [
                "config",
                "update",
                "--env",
                "dev",
                "--audit-log-euid-prefix",
                "TAG",
                "--support-email",
                "support@example.com",
            ],
            True,
        ),
    ]


def test_ensure_tapdb_namespace_config_creates_scoped_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".config" / "tapdb" / "bloom" / "bloom-local2" / "tapdb-config.yaml"
    monkeypatch.setattr(
        db_commands,
        "_runtime_env",
        lambda: {
            "TAPDB_CLIENT_ID": "bloom",
            "TAPDB_DATABASE_NAME": "bloom",
            "TAPDB_CONFIG_PATH": str(config_path),
        },
    )
    monkeypatch.setattr(db_commands, "_local_pg_port", lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT))
    monkeypatch.setattr(db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT))
    monkeypatch.setattr(db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "TAG")
    monkeypatch.setattr(db_commands, "_tapdb_support_email", lambda _env: "support@example.com")
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda *_args, **_kwargs: 0)

    db_commands._ensure_tapdb_namespace_config("dev")

    assert config_path.parent.exists()


def test_db_seed_calls_tapdb_template_loader(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tapdb_seed: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_seed_tapdb_templates",
        lambda env_name, include_workflow, overwrite: tapdb_seed.append(
            (env_name, include_workflow, overwrite)
        ),
    )

    result = runner.invoke(cli_app, ["db", "seed"])
    assert result.exit_code == 0
    assert tapdb_seed == [("dev", False, False)]
