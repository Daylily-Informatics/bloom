"""Tests for the Bloom CLI surface and Bloom-specific config/server wiring."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bloom_lims.cli import (
    _enforce_conda_env_contract,
    _strip_skip_conda_env_check_flag,
    build_app,
    config_extra,
)

try:
    from cli_core_yo.certs import ResolvedHttpsCerts
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class ResolvedHttpsCerts:
        cert_path: Path
        key_path: Path
        source: str = "ensure_certs"

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
        assert "nuke" in result.output
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

    def test_config_status_prints_deploy_name(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "bringup")

        result = runner.invoke(cli_app, ["config", "status"])

        assert result.exit_code == 0
        assert "deploy-name" in result.output
        assert "bringup" in result.output

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

    def test_config_doctor_expects_deployment_scoped_conda_env(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "bringup")
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "BLOOM-bringup")
        monkeypatch.setattr(
            config_extra,
            "run_schema_drift_check",
            lambda env_name: {
                "status": "clean",
                "checked_at": "2026-03-29T12:00:00+00:00",
                "environment": env_name,
                "tool_version": "4.1.1",
                "summary": "ok",
                "report": {"counts": {"expected": 12, "live": 12}},
                "stderr": "",
            },
        )
        monkeypatch.setattr(config_extra, "validate_settings", lambda: [])
        monkeypatch.setattr(config_extra, "assert_tapdb_version", lambda: "4.1.1")

        result = runner.invoke(cli_app, ["config", "doctor"])

        assert result.exit_code == 0
        assert "Conda environment: BLOOM-bringup" in result.output
        assert "expected: BLOOM)" not in result.output

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


class TestServerTlsBehavior:
    def _fake_settings(self):
        return SimpleNamespace(
            host="0.0.0.0",
            port=8912,
            environment="development",
            auth=SimpleNamespace(
                cognito_user_pool_id="pool",
                cognito_client_id="client",
                cognito_domain="bloom.auth.us-east-1.amazoncognito.com",
                cognito_redirect_uri="https://localhost:8912/auth/callback",
                cognito_logout_redirect_uri="https://localhost:8912/",
            ),
            atlas=SimpleNamespace(webhook_secret="secret"),
        )

    def _patch_startup_dependencies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_settings = self._fake_settings()
        monkeypatch.setattr(server_commands, "get_settings", lambda: fake_settings)
        monkeypatch.setattr(server_commands, "apply_runtime_environment", lambda settings: settings)
        monkeypatch.setattr(server_commands, "atlas_webhook_secret_warning", lambda _settings: None)
        monkeypatch.setattr(
            server_commands,
            "get_tapdb_db_config",
            lambda: {"host": "localhost", "port": 5432, "database": "bloom"},
        )

    def test_server_start_uses_shared_dayhoff_certs_and_reports_https(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        self._patch_startup_dependencies(monkeypatch)

        calls: dict[str, object] = {}
        cert_pair = ResolvedHttpsCerts(
            cert_path=tmp_path / "shared" / "cert.pem",
            key_path=tmp_path / "shared" / "key.pem",
            source="shared-state",
        )

        def fake_resolve_https_certs(**kwargs):
            calls["resolve_kwargs"] = kwargs
            cert_pair.cert_path.parent.mkdir(parents=True, exist_ok=True)
            cert_pair.cert_path.write_text("cert", encoding="utf-8")
            cert_pair.key_path.write_text("key", encoding="utf-8")
            return cert_pair

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["cwd"] = kwargs.get("cwd")
            calls["env"] = kwargs.get("env")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(server_commands, "resolve_https_certs", fake_resolve_https_certs)
        monkeypatch.setattr(server_commands.subprocess, "run", fake_run)

        result = runner.invoke(cli_app, ["server", "start", "--foreground"])

        assert result.exit_code == 0, result.output
        assert "https://localhost:8912" in result.output
        assert calls["resolve_kwargs"]["shared_certs_dir"] == server_commands._deployment_shared_certs_dir()
        assert calls["resolve_kwargs"]["fallback_certs_dir"] == server_commands.PROJECT_ROOT / "certs"
        assert "--ssl-certfile" in calls["cmd"]
        assert str(cert_pair.cert_path) in calls["cmd"]
        assert "--ssl-keyfile" in calls["cmd"]
        assert str(cert_pair.key_path) in calls["cmd"]
        assert json.loads(server_commands._runtime_meta_file().read_text(encoding="utf-8")) == {
            "ssl_enabled": True
        }

    def test_server_uses_shared_cli_core_cert_resolver(self) -> None:
        assert server_commands.resolve_https_certs.__module__ == "cli_core_yo.certs"
        assert server_commands.shared_dayhoff_certs_dir.__module__ == "cli_core_yo.certs"

    def test_server_start_no_ssl_skips_cert_resolution_and_reports_http(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_startup_dependencies(monkeypatch)

        resolve_called = False
        calls: dict[str, object] = {}

        def fake_resolve_https_certs(**_kwargs):
            nonlocal resolve_called
            resolve_called = True
            raise AssertionError("resolve_https_certs should not be called for --no-ssl")

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(server_commands, "resolve_https_certs", fake_resolve_https_certs)
        monkeypatch.setattr(server_commands.subprocess, "run", fake_run)

        result = runner.invoke(cli_app, ["server", "start", "--foreground", "--no-ssl"])

        assert result.exit_code == 0, result.output
        assert "http://localhost:8912" in result.output
        assert resolve_called is False
        assert "--ssl-certfile" not in calls["cmd"]
        assert "--ssl-keyfile" not in calls["cmd"]
        assert json.loads(server_commands._runtime_meta_file().read_text(encoding="utf-8")) == {
            "ssl_enabled": False
        }

    def test_server_status_uses_runtime_meta_scheme(
        self,
        runner: CliRunner,
        cli_app,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".local" / "state" / "bloom"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "server.pid").write_text("321", encoding="utf-8")
        (state_dir / "server-meta.json").write_text(
            json.dumps({"ssl_enabled": False}),
            encoding="utf-8",
        )
        monkeypatch.setattr(server_commands.os, "kill", lambda pid, sig: None)

        result = runner.invoke(cli_app, ["server", "status"])

        assert result.exit_code == 0
        assert "http://localhost:8912" in result.output
        assert "Running (HTTP, PID 321)" in server_commands.server_status_label()


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
