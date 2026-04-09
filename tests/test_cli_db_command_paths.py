"""Additional coverage for Bloom DB CLI command wiring."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bloom_lims.cli import build_app
from bloom_lims.config import DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT, DEFAULT_BLOOM_WEB_PORT

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
    monkeypatch.setattr(
        db_commands,
        "_runtime_env",
        lambda: {
            "AWS_PROFILE": "lsmc",
            "AWS_REGION": "us-west-2",
            "AWS_DEFAULT_REGION": "us-west-2",
            "MERIDIAN_DOMAIN_CODE": "Z",
            "TAPDB_APP_CODE": "B",
        },
    )
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            config_path="/tmp/bloom-tapdb.yaml",
            env="dev",
        ),
    )
    captured: dict[str, dict[str, str]] = {}

    def fake_run(cmd, env=None, **_kwargs):
        captured["env"] = env
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(db_commands.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        db_commands._run_tapdb(["db", "setup"], check=True)

    assert exc.value.code == 7
    assert captured["env"]["MERIDIAN_DOMAIN_CODE"] == "Z"
    assert captured["env"]["TAPDB_APP_CODE"] == "B"


def test_run_tapdb_returns_nonzero_when_check_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_commands, "_tapdb_base_cmd", lambda: ["tapdb"])
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {})
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            config_path="/tmp/bloom-tapdb.yaml",
            env="dev",
        ),
    )
    monkeypatch.setattr(
        db_commands.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3),
    )

    assert db_commands._run_tapdb(["db", "setup"], check=False) == 3


def test_update_tapdb_namespace_config_uses_db_config_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "audit.bloom"
    )
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._update_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "db-config",
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
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            client_id="bloom",
            database_name="bloom",
            config_path="/tmp/.config/tapdb/bloom/bloom-local2/tapdb-config.yaml",
            env="dev",
            aws_profile="lsmc",
            aws_region="us-west-2",
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_local_pg_port",
        lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT),
    )
    monkeypatch.setattr(
        db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT)
    )
    monkeypatch.setattr(db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "BBL")
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._ensure_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "db-config",
                "init",
                "--client-id",
                "bloom",
                "--database-name",
                "bloom",
                "--euid-client-code",
                "B",
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
                "db-config",
                "update",
                "--env",
                "dev",
                "--audit-log-euid-prefix",
                "BBL",
                "--support-email",
                "support@example.com",
            ],
            True,
        ),
    ]


def test_ensure_tapdb_namespace_config_creates_scoped_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = (
        tmp_path / ".config" / "tapdb" / "bloom" / "bloom-local2" / "tapdb-config.yaml"
    )
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            client_id="bloom",
            database_name="bloom",
            config_path=str(config_path),
            env="dev",
            aws_profile="lsmc",
            aws_region="us-west-2",
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_local_pg_port",
        lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT),
    )
    monkeypatch.setattr(
        db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT)
    )
    monkeypatch.setattr(db_commands, "_tapdb_audit_log_euid_prefix", lambda _env: "BBL")
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda *_args, **_kwargs: 0)

    db_commands._ensure_tapdb_namespace_config("dev")

    assert config_path.parent.exists()


def test_resolve_tapdb_schema_source_skips_dayhoff_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sibling_schema = tmp_path / "daylily-tapdb" / "schema" / "tapdb_schema.sql"
    sibling_schema.parent.mkdir(parents=True, exist_ok=True)
    sibling_schema.write_text("-- sibling schema\n", encoding="utf-8")

    artifact_pkg = (
        tmp_path
        / ".dayhoff"
        / "local"
        / "lsmc5"
        / "repos"
        / "daylily-tapdb"
        / "daylily_tapdb"
        / "__init__.py"
    )
    artifact_pkg.parent.mkdir(parents=True, exist_ok=True)
    artifact_pkg.write_text("# artifact package\n", encoding="utf-8")

    monkeypatch.setattr(db_commands, "_bloom_root", lambda: tmp_path / "bloom")
    monkeypatch.setattr(
        db_commands.importlib,
        "import_module",
        lambda _name: SimpleNamespace(__file__=str(artifact_pkg)),
    )

    assert db_commands._resolve_tapdb_schema_source() == sibling_schema


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


@pytest.mark.parametrize(
    ("force", "expected_args"),
    [
        (False, ["db", "schema", "reset", "dev"]),
        (True, ["db", "schema", "reset", "dev", "--force"]),
    ],
)
def test_db_nuke_calls_tapdb_schema_reset(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
    expected_args: list[str],
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    argv = ["db", "nuke"]
    if force:
        argv.append("--force")

    result = runner.invoke(cli_app, argv)
    assert result.exit_code == 0
    assert calls == [(expected_args, True)]
