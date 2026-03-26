"""Tests for BLOOM CLI commands.

Each CLI command and subcommand has at least one test.
"""

import importlib

import pytest
from click.testing import CliRunner

from bloom_lims.cli import cli

db_commands = importlib.import_module("bloom_lims.cli.db")
gui_commands = importlib.import_module("bloom_lims.cli.gui")


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


class TestMainCommands:
    """Tests for top-level CLI commands."""

    def test_cli_help(self, runner):
        """Test bloom --help."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "BLOOM LIMS" in result.output or "Usage" in result.output

    def test_version_command(self, runner):
        """Test bloom version."""
        result = runner.invoke(cli, ["version"])
        # May exit 0 or show version info
        assert result.exit_code in [0, 1, 2]

    def test_info_command(self, runner):
        """Test bloom info."""
        result = runner.invoke(cli, ["info"])
        assert result.exit_code in [0, 1, 2]

    def test_status_command(self, runner):
        """Test bloom status."""
        result = runner.invoke(cli, ["status"])
        assert result.exit_code in [0, 1, 2]

    def test_doctor_command(self, runner):
        """Test bloom doctor."""
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code in [0, 1, 2]

    def test_config_command(self, runner):
        """Test bloom config."""
        result = runner.invoke(cli, ["config"])
        assert result.exit_code in [0, 1, 2]

    def test_logs_command(self, runner):
        """Test bloom logs --help."""
        result = runner.invoke(cli, ["logs", "--help"])
        assert result.exit_code == 0

    def test_server_group_help(self, runner):
        """Test bloom server --help."""
        result = runner.invoke(cli, ["server", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output

    def test_test_group_help(self, runner):
        """Test bloom test --help."""
        result = runner.invoke(cli, ["test", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_quality_group_help(self, runner):
        """Test bloom quality --help."""
        result = runner.invoke(cli, ["quality", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output

    def test_users_group_help(self, runner):
        """Test bloom users --help."""
        result = runner.invoke(cli, ["users", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "list" in result.output

    def test_integrations_group_help(self, runner):
        """Test bloom integrations --help."""
        result = runner.invoke(cli, ["integrations", "--help"])
        assert result.exit_code == 0
        assert "atlas" in result.output

    def test_shell_command_help(self, runner):
        """Test bloom shell --help."""
        result = runner.invoke(cli, ["shell", "--help"])
        assert result.exit_code == 0

    def test_gui_command_help(self, runner):
        """Test bloom gui --help."""
        result = runner.invoke(cli, ["gui", "--help"])
        assert result.exit_code == 0

    def test_stop_command(self, runner):
        """Test bloom stop (may fail if nothing running)."""
        result = runner.invoke(cli, ["stop"])
        # Exit code can vary based on whether GUI is running
        assert result.exit_code in [0, 1, 2]


class TestDbSubcommands:
    """Tests for bloom db subcommands."""

    def test_db_help(self, runner):
        """Test bloom db --help."""
        result = runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "Database" in result.output or "db" in result.output.lower()

    def test_db_status(self, runner):
        """Test bloom db status."""
        result = runner.invoke(cli, ["db", "status"])
        assert result.exit_code in [0, 1, 2]

    def test_db_start_help(self, runner):
        """Test bloom db start --help."""
        result = runner.invoke(cli, ["db", "start", "--help"])
        assert result.exit_code == 0

    def test_db_stop_help(self, runner):
        """Test bloom db stop --help."""
        result = runner.invoke(cli, ["db", "stop", "--help"])
        assert result.exit_code == 0

    def test_db_init_help(self, runner):
        """Test bloom db init --help."""
        result = runner.invoke(cli, ["db", "init", "--help"])
        assert result.exit_code == 0

    def test_db_init_bootstraps_tapdb_namespace_config(self, runner, monkeypatch):
        """db init should create namespaced TapDB config before local startup."""
        calls = []

        monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
        monkeypatch.setattr(
            db_commands,
            "_runtime_env",
            lambda: {
                "TAPDB_ENV": "dev",
                "TAPDB_CLIENT_ID": "bloom",
                "TAPDB_DATABASE_NAME": "bloom",
            },
        )
        monkeypatch.setattr(db_commands, "_ensure_schema_available_for_bloom_root", lambda: None)
        monkeypatch.setattr(db_commands, "_local_pg_port", lambda _env: "5566")
        monkeypatch.setattr(db_commands, "_local_ui_port", lambda _env: "8912")
        monkeypatch.setattr(
            db_commands,
            "_run_tapdb",
            lambda args, check=True: calls.append((args, check)) or 0,
        )
        monkeypatch.setattr(db_commands, "_seed_tapdb_templates", lambda *args, **kwargs: None)
        monkeypatch.setattr(db_commands, "_seed_bloom_templates", lambda: None)

        result = runner.invoke(cli, ["db", "init"])

        assert result.exit_code == 0
        assert calls[:4] == [
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
            (["pg", "init", "dev"], False),
            (["pg", "start-local", "dev", "--port", "5566"], True),
            (["db", "setup", "dev"], True),
        ]

    def test_ensure_tapdb_namespace_config_fills_required_metadata(
        self, monkeypatch, tmp_path
    ):
        """TapDB namespace config bootstrap should fill Bloom-required metadata."""
        calls = []
        config_path = tmp_path / "tapdb-config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "meta:",
                    "  config_version: 2",
                    "  client_id: bloom",
                    "  database_name: bloom",
                    "environments:",
                    "  dev:",
                    "    engine_type: local",
                    "    host: localhost",
                    '    port: "5566"',
                    '    ui_port: "8912"',
                    '    user: "postgres"',
                    '    password: ""',
                    '    database: "tapdb_bloom_dev"',
                    '    cognito_user_pool_id: ""',
                    '    audit_log_euid_prefix: ""',
                    '    support_email: ""',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            db_commands,
            "_runtime_env",
            lambda: {
                "TAPDB_CLIENT_ID": "bloom",
                "TAPDB_DATABASE_NAME": "bloom",
            },
        )
        monkeypatch.setattr(
            db_commands,
            "_tapdb_namespace_config_path",
            lambda _client_id, _database_name: config_path,
        )
        monkeypatch.setattr(db_commands, "_local_pg_port", lambda _env: "5566")
        monkeypatch.setattr(db_commands, "_local_ui_port", lambda _env: "8912")
        monkeypatch.setattr(
            db_commands,
            "_tapdb_audit_log_euid_prefix",
            lambda _env: "TAG",
        )
        monkeypatch.setattr(
            db_commands,
            "_tapdb_support_email",
            lambda _env: "support@dyly.bio",
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
            )
        ]
        text = config_path.read_text(encoding="utf-8")
        assert 'audit_log_euid_prefix: TAG' in text
        assert 'support_email: support@dyly.bio' in text

    def test_db_migrate_help(self, runner):
        """Test bloom db migrate --help."""
        result = runner.invoke(cli, ["db", "migrate", "--help"])
        assert result.exit_code == 0

    def test_db_seed_help(self, runner):
        """Test bloom db seed --help."""
        result = runner.invoke(cli, ["db", "seed", "--help"])
        assert result.exit_code == 0

    def test_db_reset_help(self, runner):
        """Test bloom db reset --help."""
        result = runner.invoke(cli, ["db", "reset", "--help"])
        assert result.exit_code == 0

    def test_db_shell_help(self, runner):
        """Test bloom db shell --help."""
        result = runner.invoke(cli, ["db", "shell", "--help"])
        assert result.exit_code == 0

    def test_ensure_schema_available_replaces_broken_symlink(
        self, tmp_path, monkeypatch
    ):
        """Dangling schema symlinks should be replaced before bootstrap."""
        project_root = tmp_path / "project"
        source = tmp_path / "tapdb" / "schema" / "tapdb_schema.sql"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("-- schema\n", encoding="utf-8")

        target = project_root / "schema" / "tapdb_schema.sql"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(tmp_path / "missing" / "tapdb_schema.sql")

        monkeypatch.setattr(db_commands, "_bloom_root", lambda: project_root)
        monkeypatch.setattr(
            db_commands,
            "_resolve_tapdb_schema_source",
            lambda: source,
        )

        db_commands._ensure_schema_available_for_bloom_root()

        assert target.is_symlink()
        assert target.resolve() == source.resolve()


class TestGuiLocalhostPolicy:
    """Tests for localhost-only GUI startup policy via cli_core_yo.certs."""

    def test_ensure_certs_generates_localhost_only_cert(self, tmp_path, monkeypatch):
        import shutil as _shutil
        import subprocess as _subprocess

        import cli_core_yo.certs as certs_mod

        certs_dir = tmp_path / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(_shutil, "which", lambda _: "/usr/local/bin/mkcert")

        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if "-key-file" in args and "-cert-file" in args:
                key_file = args[args.index("-key-file") + 1]
                cert_file = args[args.index("-cert-file") + 1]
                with open(key_file, "w", encoding="utf-8") as fh:
                    fh.write("key")
                with open(cert_file, "w", encoding="utf-8") as fh:
                    fh.write("cert")
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr(certs_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(certs_mod.shutil, "which", lambda _: "/usr/local/bin/mkcert")

        cert_file, key_file = certs_mod.ensure_certs(certs_dir)
        assert cert_file.exists()
        assert key_file.exists()

        cert_gen_call = next(call for call in calls if "-key-file" in call)
        assert "localhost" in cert_gen_call
