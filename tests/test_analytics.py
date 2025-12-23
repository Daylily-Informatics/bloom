"""
Tests for Analytics Dashboard Integration

These tests verify that analytics SQL views and dashboard definitions
are properly structured and contain required elements.
"""

import json
import os
import re
from pathlib import Path

import pytest


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent
ANALYTICS_DIR = PROJECT_ROOT / "analytics"


class TestAnalyticsDirectoryStructure:
    """Tests for analytics directory structure."""

    def test_analytics_directory_exists(self):
        """Test that analytics directory exists."""
        assert ANALYTICS_DIR.exists()
        assert ANALYTICS_DIR.is_dir()

    def test_sql_views_directory_exists(self):
        """Test that sql_views directory exists."""
        sql_dir = ANALYTICS_DIR / "sql_views"
        assert sql_dir.exists()

    def test_dashboards_directory_exists(self):
        """Test that dashboards directory exists."""
        dashboards_dir = ANALYTICS_DIR / "dashboards"
        assert dashboards_dir.exists()

    def test_metabase_directory_exists(self):
        """Test that metabase directory exists."""
        metabase_dir = ANALYTICS_DIR / "metabase"
        assert metabase_dir.exists()


class TestSQLViews:
    """Tests for SQL analytics views."""

    @pytest.fixture
    def sql_content(self):
        """Load install_views.sql content."""
        sql_path = ANALYTICS_DIR / "sql_views" / "install_views.sql"
        assert sql_path.exists(), "install_views.sql not found"
        return sql_path.read_text()

    def test_install_views_exists(self):
        """Test that install_views.sql exists."""
        sql_path = ANALYTICS_DIR / "sql_views" / "install_views.sql"
        assert sql_path.exists()

    def test_contains_sample_throughput_view(self, sql_content):
        """Test that v_sample_throughput view is defined."""
        assert "v_sample_throughput" in sql_content
        assert "CREATE" in sql_content

    def test_contains_workflow_bottlenecks_view(self, sql_content):
        """Test that v_workflow_bottlenecks view is defined."""
        assert "v_workflow_bottlenecks" in sql_content

    def test_contains_equipment_utilization_view(self, sql_content):
        """Test that v_equipment_utilization view is defined."""
        assert "v_equipment_utilization" in sql_content

    def test_contains_turnaround_times_view(self, sql_content):
        """Test that v_turnaround_times view is defined."""
        assert "v_turnaround_times" in sql_content

    def test_contains_audit_activity_view(self, sql_content):
        """Test that v_audit_activity view is defined."""
        assert "v_audit_activity" in sql_content

    def test_contains_object_counts_view(self, sql_content):
        """Test that v_object_counts view is defined."""
        assert "v_object_counts" in sql_content

    def test_contains_daily_summary_view(self, sql_content):
        """Test that v_daily_summary view is defined."""
        assert "v_daily_summary" in sql_content

    def test_views_use_generic_instance_table(self, sql_content):
        """Test that views reference generic_instance table."""
        assert "generic_instance" in sql_content

    def test_views_have_comments(self, sql_content):
        """Test that views have documentation comments."""
        assert "COMMENT ON VIEW" in sql_content


class TestDashboardDefinitions:
    """Tests for dashboard JSON definitions."""

    def test_operations_overview_exists(self):
        """Test that operations_overview.json exists."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "operations_overview.json"
        assert dashboard_path.exists()

    def test_turnaround_times_exists(self):
        """Test that turnaround_times.json exists."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "turnaround_times.json"
        assert dashboard_path.exists()

    def test_equipment_utilization_exists(self):
        """Test that equipment_utilization.json exists."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "equipment_utilization.json"
        assert dashboard_path.exists()

    def test_operations_overview_valid_json(self):
        """Test that operations_overview.json is valid JSON."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "operations_overview.json"
        content = dashboard_path.read_text()
        data = json.loads(content)  # Will raise if invalid
        assert "name" in data
        assert "cards" in data

    def test_dashboard_has_required_fields(self):
        """Test that dashboard definitions have required fields."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "operations_overview.json"
        data = json.loads(dashboard_path.read_text())
        
        assert "name" in data
        assert "description" in data
        assert "cards" in data
        assert isinstance(data["cards"], list)
        assert len(data["cards"]) > 0

    def test_dashboard_cards_have_required_fields(self):
        """Test that dashboard cards have required fields."""
        dashboard_path = ANALYTICS_DIR / "dashboards" / "operations_overview.json"
        data = json.loads(dashboard_path.read_text())
        
        for card in data["cards"]:
            assert "id" in card
            assert "title" in card
            assert "type" in card
            assert "query" in card


class TestMetabaseSetup:
    """Tests for Metabase docker-compose setup."""

    def test_docker_compose_exists(self):
        """Test that docker-compose.yml exists."""
        compose_path = ANALYTICS_DIR / "metabase" / "docker-compose.yml"
        assert compose_path.exists()

    def test_run_script_exists(self):
        """Test that run_metabase.sh exists."""
        script_path = ANALYTICS_DIR / "metabase" / "run_metabase.sh"
        assert script_path.exists()

    def test_run_script_is_executable(self):
        """Test that run_metabase.sh is executable."""
        script_path = ANALYTICS_DIR / "metabase" / "run_metabase.sh"
        assert os.access(script_path, os.X_OK)

    def test_docker_compose_defines_metabase_service(self):
        """Test that docker-compose defines metabase service."""
        compose_path = ANALYTICS_DIR / "metabase" / "docker-compose.yml"
        content = compose_path.read_text()
        assert "metabase" in content.lower()
        assert "services" in content

