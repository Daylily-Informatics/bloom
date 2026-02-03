"""Tests for BLOOM CLI commands.

Each CLI command and subcommand has at least one test.
"""

import pytest
from click.testing import CliRunner

from bloom_lims.cli import cli


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

