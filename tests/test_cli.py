"""Tests for the Bloom CLI surface and Bloom-specific config/server wiring."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bloom_lims.cli import (
    _enforce_conda_env_contract,
    _strip_skip_conda_env_check_flag,
    build_app,
)
from bloom_lims.cli import config_extra

server_commands = importlib.import_module("bloom_lims.cli.server")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return build_app()


class TestMainCommands:
    def test_cli_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0
        assert "│ server" in result.output
        assert "│ config" in result.output
        assert "│ db" in result.output
        assert "│ gui" not in result.output
        assert "│ doctor" not in result.output
        assert "│ status" not in result.output
        assert "│ logs" not in result.output
        assert "│ shell" not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["gui"],
            ["stop"],
            ["status"],
            ["logs"],
            ["doctor"],
            ["shell"],
            ["config-validate"],
        ],
    )
    def test_removed_root_aliases(
        self, runner: CliRunner, cli_app, argv: list[str]
    ) -> None:
        result = runner.invoke(cli_app, argv)
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_version_command(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["version"])
        assert result.exit_code == 0
        assert "BLOOM LIMS" in result.output

    def test_info_command(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["info"])
        assert result.exit_code == 0
        assert "Project Root" in result.output
        assert "Dev Server" in result.output

    def test_config_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["config", "--help"])
        assert result.exit_code == 0
        for command in [
            "path",
            "init",
            "show",
            "validate",
            "edit",
            "reset",
            "shell",
            "doctor",
            "status",
        ]:
            assert command in result.output

    def test_server_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["server", "--help"])
        assert result.exit_code == 0
        for command in ["start", "stop", "status", "logs"]:
            assert command in result.output

    def test_db_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["db", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "seed" in result.output
        assert "reset" in result.output
        assert "start" not in result.output
        assert "stop" not in result.output
        assert "status" not in result.output
        assert "migrate" not in result.output
        assert "shell" not in result.output
        assert "auth-setup" not in result.output

    def test_quality_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["quality", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output

    def test_users_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["users", "--help"])
        assert result.exit_code == 0
        assert "issue-token" in result.output
        assert "list" not in result.output
        assert "add" not in result.output

    def test_integrations_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["integrations", "--help"])
        assert result.exit_code == 0

    def test_cli_requires_hyphenated_conda_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "BLOOM")
        with pytest.raises(SystemExit, match="deployment-scoped conda environment name with '-'"):
            _enforce_conda_env_contract(["db", "init"])

    def test_cli_requires_active_conda_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
        with pytest.raises(
            SystemExit, match="requires an active deployment-scoped conda environment"
        ):
            _enforce_conda_env_contract(["db", "init"])

    def test_cli_accepts_hyphenated_conda_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "BLOOM-local2")
        _enforce_conda_env_contract(["db", "init"])

    def test_cli_skip_conda_env_check_flag_is_stripped(self) -> None:
        args, skip = _strip_skip_conda_env_check_flag(
            ["--skip-conda-env-check", "db", "init"]
        )
        assert skip is True
        assert args == ["db", "init"]

    def test_config_doctor_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["config", "doctor", "--help"])
        assert result.exit_code == 0

    def test_config_doctor_reports_schema_drift_without_failing(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            config_extra,
            "run_schema_drift_check",
            lambda env_name: {
                "status": "drift",
                "checked_at": "2026-03-29T12:00:00+00:00",
                "environment": env_name,
                "tool_version": "3.0.9",
                "summary": "expected=12 live=13",
                "report": {"counts": {"expected": 12, "live": 13}},
                "stderr": "",
            },
        )
        monkeypatch.setattr(config_extra, "validate_settings", lambda: [])
        monkeypatch.setattr(config_extra, "assert_tapdb_version", lambda: "3.0.9")

        result = runner.invoke(cli_app, ["config", "doctor"])
        assert result.exit_code == 0
        assert "schema drift detected" in result.output.lower()
        assert "report only" in result.output.lower()
        drift_report = tmp_path / ".local" / "state" / "bloom" / "schema_drift.json"
        assert drift_report.exists()
        assert "expected=12 live=13" in drift_report.read_text(encoding="utf-8")

    def test_config_shell_help(self, runner: CliRunner, cli_app) -> None:
        result = runner.invoke(cli_app, ["config", "shell", "--help"])
        assert result.exit_code == 0


class TestConfigValidation:
    def test_config_init_then_validate(
        self, runner: CliRunner, cli_app, tmp_path: Path
    ) -> None:
        result = runner.invoke(cli_app, ["config", "init"])
        assert result.exit_code == 0

        config_path = tmp_path / ".config" / "bloom-local" / "bloom-config-local.yaml"
        assert config_path.exists()

        result = runner.invoke(cli_app, ["config", "validate"])
        assert result.exit_code == 0
        assert "Config is valid" in result.output

    def test_config_validate_rejects_invalid_yaml(
        self,
        runner: CliRunner,
        cli_app,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / ".config" / "bloom-local" / "bloom-config-local.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("auth:\n  cognito_user_pool_id: [\n", encoding="utf-8")

        result = runner.invoke(cli_app, ["config", "validate"])
        assert result.exit_code != 0
        assert "YAML parse error" in result.output

    def test_config_validate_rejects_semantic_errors(
        self,
        runner: CliRunner,
        cli_app,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / ".config" / "bloom-local" / "bloom-config-local.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("environment: invalid\n", encoding="utf-8")

        result = runner.invoke(cli_app, ["config", "validate"])
        assert result.exit_code != 0
        assert "environment" in result.output


class TestServerState:
    def test_server_status_ignores_legacy_pid_files(
        self,
        runner: CliRunner,
        cli_app,
        tmp_path: Path,
    ) -> None:
        legacy_pid = tmp_path / ".bloom" / "server.pid"
        legacy_pid.parent.mkdir(parents=True, exist_ok=True)
        legacy_pid.write_text("4321", encoding="utf-8")

        result = runner.invoke(cli_app, ["server", "status"])
        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_server_logs_ignores_legacy_logs(
        self,
        runner: CliRunner,
        cli_app,
        tmp_path: Path,
    ) -> None:
        legacy_log = tmp_path / ".bloom" / "logs" / "server_20260101_000000.log"
        legacy_log.parent.mkdir(parents=True, exist_ok=True)
        legacy_log.write_text("legacy log\n", encoding="utf-8")

        result = runner.invoke(cli_app, ["server", "logs", "--service", "server"])
        assert result.exit_code == 0
        assert "No log files found" in result.output

    def test_info_reports_server_status_from_xdg_state(
        self,
        runner: CliRunner,
        cli_app,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state_dir = tmp_path / ".local" / "state" / "bloom"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "server.pid").write_text("321", encoding="utf-8")
        monkeypatch.setattr(server_commands.os, "kill", lambda pid, sig: None)

        result = runner.invoke(cli_app, ["info"])
        assert result.exit_code == 0
        assert "Dev Server" in result.output
        assert "321" in result.output


class TestGuiLocalhostPolicy:
    def test_ensure_certs_generates_localhost_only_cert(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import cli_core_yo.certs as certs_mod

        certs_dir = tmp_path / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)

        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if "-key-file" in args and "-cert-file" in args:
                key_file = args[args.index("-key-file") + 1]
                cert_file = args[args.index("-cert-file") + 1]
                Path(key_file).write_text("key", encoding="utf-8")
                Path(cert_file).write_text("cert", encoding="utf-8")
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr(certs_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(
            certs_mod.shutil, "which", lambda _: "/usr/local/bin/mkcert"
        )

        cert_file, key_file = certs_mod.ensure_certs(certs_dir)
        assert cert_file.exists()
        assert key_file.exists()

        cert_gen_call = next(call for call in calls if "-key-file" in call)
        assert "localhost" in cert_gen_call
