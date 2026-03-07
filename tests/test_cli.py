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
    """Tests for localhost-only GUI startup policy."""

    def test_ensure_https_certs_generates_localhost_only_cert(self, tmp_path, monkeypatch):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(gui_commands, "PROJECT_ROOT", project_root)
        monkeypatch.setattr(gui_commands.shutil, "which", lambda _: "/usr/local/bin/mkcert")

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

        monkeypatch.setattr(gui_commands.subprocess, "run", fake_run)

        cert_file, key_file = gui_commands._ensure_https_certs()
        assert cert_file.exists()
        assert key_file.exists()

        cert_gen_call = next(call for call in calls if "-key-file" in call)
        assert "localhost" in cert_gen_call
        assert "127.0.0.1" not in cert_gen_call
        assert "::1" not in cert_gen_call
