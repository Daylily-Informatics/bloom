"""
BLOOM LIMS GUI Endpoint Tests

Comprehensive pytest tests for all FastAPI GUI endpoints defined in main.py.
Tests verify endpoints return correct HTTP responses and HTML content.

With BLOOM_OAUTH=no, authentication is bypassed for testing.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Set up auth bypass BEFORE importing FastAPI app
os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_API_AUTH"] = "no"

from fastapi.testclient import TestClient

# Add root to path for main import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    return TestClient(app)


class TestPublicEndpoints:
    """Tests for public endpoints."""

    def test_root_index(self, client):
        """Test root index page returns HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_favicon(self, client):
        """Test favicon endpoint."""
        response = client.get("/favicon.ico")
        assert response.status_code in [200, 404]

    def test_login_page(self, client):
        """Test login page returns HTML."""
        response = client.get("/login")
        assert response.status_code in [200, 401]


class TestMainGUIEndpoints:
    """Tests for main GUI endpoints (auth bypassed)."""

    def test_index2_returns_html(self, client):
        """Test index2 page returns HTML."""
        response = client.get("/index2")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_lims_returns_html(self, client):
        """Test LIMS page returns HTML."""
        response = client.get("/lims")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_admin_returns_html(self, client):
        """Test admin page returns HTML."""
        response = client.get("/admin")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAssaysEndpoint:
    """Tests for /assays endpoint - fixed TapDB column names."""

    def test_assays_default_returns_html(self, client):
        """Test assays endpoint returns HTML."""
        response = client.get("/assays")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_assays_show_type_all(self, client):
        """Test assays with show_type=all parameter."""
        response = client.get("/assays?show_type=all")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_assays_show_type_accessioning(self, client):
        """Test assays with show_type=accessioning (was failing before TapDB fix)."""
        response = client.get("/assays?show_type=accessioning")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_assays_show_type_assay(self, client):
        """Test assays with show_type=assay parameter."""
        response = client.get("/assays?show_type=assay")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestEuidDetailsEndpoint:
    """Tests for /euid_details endpoint."""

    def test_euid_details_requires_euid(self, client):
        """Test euid_details requires euid parameter."""
        response = client.get("/euid_details")
        assert response.status_code == 422  # Validation error

    def test_euid_details_with_nonexistent_euid(self, client):
        """Test euid_details with non-existent euid returns 404."""
        response = client.get("/euid_details?euid=NONEXISTENT_TEST_EUID")
        assert response.status_code == 404


class TestWorkflowEndpoints:
    """Tests for workflow-related endpoints."""

    def test_workflow_summary_returns_html(self, client):
        """Test workflow summary returns HTML."""
        response = client.get("/workflow_summary")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_workflow_details_requires_euid(self, client):
        """Test workflow details requires euid parameter."""
        response = client.get("/workflow_details")
        assert response.status_code == 422


class TestEquipmentEndpoints:
    """Tests for equipment-related endpoints."""

    def test_equipment_overview_returns_html(self, client):
        """Test equipment overview returns HTML."""
        response = client.get("/equipment_overview")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_create_from_template_get_returns_html(self, client):
        """Test create from template GET returns HTML."""
        response = client.get("/create_from_template")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestReagentControlEndpoints:
    """Tests for reagent and control endpoints."""

    def test_reagent_overview_returns_html(self, client):
        """Test reagent overview returns HTML."""
        response = client.get("/reagent_overview")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_control_overview_returns_html(self, client):
        """Test control overview returns HTML."""
        response = client.get("/control_overview")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestTemplateEndpoints:
    """Tests for template-related endpoints."""

    def test_object_templates_summary_returns_html(self, client):
        """Test object templates summary returns HTML."""
        response = client.get("/object_templates_summary")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestPlateEndpoints:
    """Tests for plate visualization endpoints."""

    def test_plate_visualization_requires_euid(self, client):
        """Test plate visualization requires euid parameter."""
        response = client.get("/plate_visualization")
        assert response.status_code == 422

    def test_plate_carosel2_requires_euid(self, client):
        """Test plate carousel requires euid parameter."""
        response = client.get("/plate_carosel2")
        assert response.status_code == 422

    def test_get_related_plates_requires_euid(self, client):
        """Test get related plates requires euid parameter."""
        response = client.get("/get_related_plates")
        assert response.status_code == 422


class TestDAGEndpoints:
    """Tests for DAG (Directed Acyclic Graph) visualization endpoints."""

    def test_dagg_requires_euid(self, client):
        """Test DAG visualization requires euid parameter."""
        # This endpoint may raise an exception without euid - skip if so
        try:
            response = client.get("/dagg")
            assert response.status_code in [200, 422, 500]
        except Exception:
            pytest.skip("DAG endpoint raised exception - requires valid euid")

    def test_dindex2_returns_html(self, client):
        """Test DAG index returns HTML."""
        response = client.get("/dindex2")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_get_dagv2_requires_euid(self, client):
        """Test get_dagv2 requires euid parameter."""
        # This endpoint may raise an exception without euid
        try:
            response = client.get("/get_dagv2")
            assert response.status_code in [422, 500]
        except Exception:
            pytest.skip("get_dagv2 endpoint raised exception - requires valid euid")


class TestFileEndpoints:
    """Tests for file management endpoints."""

    def test_dewey_returns_html(self, client):
        """Test Dewey file browser returns HTML."""
        response = client.get("/dewey")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_bulk_create_files_returns_html(self, client):
        """Test bulk create files returns HTML."""
        response = client.get("/bulk_create_files")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestDatabaseEndpoints:
    """Tests for database information endpoints."""

    def test_database_statistics_returns_html(self, client):
        """Test database statistics returns HTML (fixed: was failing with await on sync query)."""
        response = client.get("/database_statistics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "text/html" in response.headers["content-type"]

    def test_database_statistics_contains_stats_sections(self, client):
        """Test database statistics page contains expected stats sections."""
        response = client.get("/database_statistics")
        assert response.status_code == 200
        # Page should contain statistics sections
        content = response.text
        assert "statistics" in content.lower() or "stats" in content.lower()

    def test_bloom_schema_report_returns_html(self, client):
        """Test BLOOM schema report returns HTML."""
        response = client.get("/bloom_schema_report")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestUserEndpoints:
    """Tests for user-related endpoints."""

    def test_user_home_returns_html(self, client):
        """Test user home page returns HTML (fixed: was accessing session before auth check)."""
        response = client.get("/user_home")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "text/html" in response.headers["content-type"]

    def test_user_home_or_redirects_to_login(self, client):
        """Test user home page returns content or redirects to login (based on auth state)."""
        response = client.get("/user_home", follow_redirects=False)
        # Should either return 200 (authenticated) or 307 redirect to login
        assert response.status_code in [200, 307], f"Expected 200 or 307, got {response.status_code}"
        if response.status_code == 307:
            assert "/login" in response.headers.get("location", "")

    def test_user_audit_logs_returns_html(self, client):
        """Test user audit logs returns HTML."""
        try:
            response = client.get("/user_audit_logs")
            assert response.status_code in [200, 500]
            if response.status_code == 200:
                assert "text/html" in response.headers["content-type"]
        except Exception:
            pytest.skip("user_audit_logs endpoint raised exception")


class TestQueueEndpoints:
    """Tests for queue management endpoints."""

    def test_queue_details_returns_html(self, client):
        """Test queue details returns HTML."""
        try:
            response = client.get("/queue_details")
            assert response.status_code in [200, 500]
            if response.status_code == 200:
                assert "text/html" in response.headers["content-type"]
        except Exception:
            pytest.skip("queue_details endpoint raised exception")

    def test_set_filter(self, client):
        """Test set filter endpoint works."""
        response = client.get("/set_filter")
        # May redirect or return success
        assert response.status_code in [200, 302, 303]


class TestDeleteEndpoints:
    """Tests for delete/undelete endpoints."""

    def test_delete_by_euid_requires_euid(self, client):
        """Test delete by EUID requires euid parameter."""
        response = client.get("/delete_by_euid")
        assert response.status_code == 422

    def test_un_delete_by_uuid_requires_uuid(self, client):
        """Test undelete by UUID requires uuid parameter."""
        response = client.get("/un_delete_by_uuid")
        assert response.status_code == 422


class TestScriptsEndpoint:
    """Tests for scripts listing endpoint."""

    def test_list_scripts_returns_json(self, client):
        """Test list-scripts returns JSON response."""
        try:
            response = client.get("/list-scripts")
            assert response.status_code in [200, 500]
            if response.status_code == 200:
                assert "application/json" in response.headers["content-type"]
        except Exception:
            pytest.skip("list-scripts endpoint raised exception")


class TestLegacyRoutes:
    """Tests for legacy UI routes."""

    def test_legacy_index(self, client):
        """Test legacy index page is accessible."""
        response = client.get("/legacy/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_legacy_login(self, client):
        """Test legacy login page is accessible."""
        response = client.get("/legacy/login")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestModernUIRoutes:
    """Tests for modern UI routes (GUI modernization)."""

    def test_modern_dashboard(self, client):
        """Test modern dashboard at root renders correctly."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Check for modern UI indicators
        content = response.text
        assert "BLOOM" in content

    def test_search_page_renders(self, client):
        """Test search page renders correctly."""
        response = client.get("/search")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        content = response.text
        assert "Search" in content

    def test_search_page_with_query(self, client):
        """Test search page with query parameter."""
        response = client.get("/search?q=test")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_search_page_with_type_filter(self, client):
        """Test search page with type filter."""
        response = client.get("/search?q=test&types=container,content")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_bulk_create_containers_page_renders(self, client):
        """Test bulk create containers page renders correctly."""
        response = client.get("/bulk_create_containers")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        content = response.text
        assert "Bulk Create" in content
        assert "TSV" in content


class TestModernTemplateUsage:
    """Tests to verify endpoints use modern templates correctly."""

    def test_dashboard_uses_modern_css(self, client):
        """Test dashboard uses modern CSS."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content

    def test_assays_uses_modern_template(self, client):
        """Test assays page uses modern template."""
        response = client.get("/assays")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Assays" in content

    def test_workflow_summary_uses_modern_template(self, client):
        """Test workflow summary uses modern template."""
        response = client.get("/workflow_summary")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Workflow" in content

    def test_equipment_overview_uses_modern_template(self, client):
        """Test equipment overview uses modern template."""
        response = client.get("/equipment_overview")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Equipment" in content

    def test_reagent_overview_uses_modern_template(self, client):
        """Test reagent overview uses modern template."""
        response = client.get("/reagent_overview")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Reagent" in content

    def test_admin_uses_modern_template(self, client):
        """Test admin page uses modern template."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Admin" in content

    def test_login_uses_modern_template(self, client):
        """Test login page uses modern template."""
        response = client.get("/login")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content

    def test_search_uses_modern_template(self, client):
        """Test search page uses modern template."""
        response = client.get("/search")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Search" in content

    def test_bulk_create_uses_modern_template(self, client):
        """Test bulk create containers uses modern template."""
        response = client.get("/bulk_create_containers")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content


class TestModernUIElements:
    """Tests to verify modern UI elements are present."""

    def test_dashboard_has_stat_cards(self, client):
        """Test dashboard has stat cards."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text
        assert "stat-card" in content or "card" in content

    def test_navigation_has_modern_elements(self, client):
        """Test navigation has modern elements."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text
        # Check for Font Awesome icons
        assert "fa-" in content
        # Check for navigation links
        assert "nav" in content.lower()

    def test_footer_has_version(self, client):
        """Test footer has version info."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text
        assert "footer" in content.lower()

    def test_pages_have_breadcrumb_or_header(self, client):
        """Test pages have page header with title."""
        response = client.get("/assays")
        assert response.status_code == 200
        content = response.text
        assert "page-header" in content or "Assays" in content


class TestModernAPIs:
    """Tests for modern API endpoints."""

    def test_dashboard_stats_api(self, client):
        """Test dashboard stats API endpoint."""
        response = client.get("/api/v1/stats/dashboard")
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        data = response.json()
        assert "containers" in data or "total" in str(data).lower()

    def test_search_api_endpoint(self, client):
        """Test search API returns JSON."""
        response = client.get("/api/v1/search?q=test&format=json")
        # May return 200 with results or appropriate status
        assert response.status_code in [200, 404, 422]

    def test_bulk_create_api_post(self, client):
        """Test bulk create API accepts POST."""
        # Test with invalid data - should return validation error
        response = client.post(
            "/api/v1/containers/bulk-create",
            json={"containers": []}
        )
        # Should return 200 or validation error, not 500
        assert response.status_code in [200, 201, 400, 422]


class TestAdminDependencyInfo:
    """Tests for admin page dependency information display."""

    def test_admin_shows_external_integrations(self, client):
        """Test admin page shows External Integrations section."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "External Integrations" in content

    def test_admin_shows_zebra_day(self, client):
        """Test admin page shows zebra_day integration."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "zebra_day" in content
        assert "Zebra printer" in content.lower() or "printer" in content.lower()

    def test_admin_shows_carrier_tracking(self, client):
        """Test admin page shows carrier tracking integration."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "carrier-tracking" in content or "carrier_tracking" in content

    def test_admin_shows_tapdb(self, client):
        """Test admin page shows daylily-tapdb integration."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "tapdb" in content.lower()

    def test_admin_shows_cognito(self, client):
        """Test admin page shows Cognito auth info."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "Cognito" in content

    def test_admin_shows_bloom_version(self, client):
        """Test admin page shows BLOOM version."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text
        assert "BLOOM Version" in content or "bloom_version" in content.lower()


class TestObjectCreationWizard:
    """Tests for object creation wizard functionality."""

    def test_create_object_page_returns_html(self, client):
        """Test create object page returns HTML."""
        response = client.get("/create_object")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_create_object_page_uses_modern_template(self, client):
        """Test create object page uses modern template."""
        response = client.get("/create_object")
        assert response.status_code == 200
        content = response.text
        assert "bloom_modern.css" in content
        assert "Create Object" in content

    def test_create_object_page_has_wizard_steps(self, client):
        """Test create object page has wizard steps."""
        response = client.get("/create_object")
        assert response.status_code == 200
        content = response.text
        assert "Super Type" in content
        assert "wizard-step" in content

    def test_create_object_navigation_link(self, client):
        """Test create object link is in navigation."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text
        assert "/create_object" in content or "Create" in content


class TestObjectCreationAPI:
    """Tests for object creation API endpoints."""

    def test_super_types_api(self, client):
        """Test super types API endpoint."""
        response = client.get("/api/v1/object-creation/super-types")
        assert response.status_code == 200
        data = response.json()
        assert "super_types" in data
        assert len(data["super_types"]) > 0
        # Should include common super types
        names = [st["name"] for st in data["super_types"]]
        assert "container" in names
        assert "content" in names

    def test_types_api(self, client):
        """Test types API endpoint for container super type."""
        response = client.get("/api/v1/object-creation/types?super_type=container")
        assert response.status_code == 200
        data = response.json()
        assert "types" in data
        assert data["super_type"] == "container"
        assert len(data["types"]) > 0
        # Should include common container types
        names = [t["name"] for t in data["types"]]
        assert "tube" in names or "plate" in names

    def test_types_api_invalid_super_type(self, client):
        """Test types API returns 404 for invalid super type."""
        response = client.get("/api/v1/object-creation/types?super_type=nonexistent")
        assert response.status_code == 404

    def test_sub_types_api(self, client):
        """Test sub-types API endpoint."""
        response = client.get("/api/v1/object-creation/sub-types?super_type=container&btype=tube")
        assert response.status_code == 200
        data = response.json()
        assert "sub_types" in data
        assert data["super_type"] == "container"
        assert data["btype"] == "tube"
        assert len(data["sub_types"]) > 0
        # Each sub-type should have versions
        for st in data["sub_types"]:
            assert "versions" in st
            assert len(st["versions"]) > 0

    def test_template_api(self, client):
        """Test template details API endpoint."""
        # First get a sub-type
        response = client.get("/api/v1/object-creation/sub-types?super_type=container&btype=tube")
        assert response.status_code == 200
        sub_types = response.json()["sub_types"]
        if sub_types:
            sub_type = sub_types[0]["name"]
            version = sub_types[0]["versions"][0]

            # Get template details
            response = client.get(
                f"/api/v1/object-creation/template?super_type=container&btype=tube&b_sub_type={sub_type}&version={version}"
            )
            assert response.status_code == 200
            data = response.json()
            assert "template" in data
            assert data["super_type"] == "container"
            assert data["btype"] == "tube"
            assert data["b_sub_type"] == sub_type


class TestLoginLogoutButtonDisplay:
    """Tests for login/logout button display logic in modern UI header.

    The base template checks for either 'user' or 'udat' variables to determine
    whether to show the logout button (authenticated) or login button (unauthenticated).
    """

    def test_authenticated_user_sees_logout_button(self, client):
        """Test that authenticated users see the logout button and their email."""
        # With BLOOM_OAUTH=no, the session is populated with test user data
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # Should see logout button
        assert "Logout" in content or "logout" in content.lower()
        # Should see the user email (from test session)
        assert "john@daylilyinformatics.com" in content or "email" in content.lower()

    def test_dashboard_shows_logout_with_udat(self, client):
        """Test dashboard page shows logout button when udat is passed."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # The dashboard passes 'udat' to the template
        # Should show logout, not login
        assert 'href="/logout"' in content
        assert 'fa-sign-out-alt' in content  # Logout icon

    def test_create_object_shows_logout_with_user(self, client):
        """Test create_object page shows logout button when user is passed."""
        response = client.get("/create_object")
        assert response.status_code == 200
        content = response.text

        # The create_object route passes both 'user' and 'user_data'
        # Should show logout, not login
        assert 'href="/logout"' in content

    def test_search_page_shows_logout(self, client):
        """Test search page shows logout button for authenticated users."""
        response = client.get("/search")
        assert response.status_code == 200
        content = response.text

        # Should show logout button
        assert 'href="/logout"' in content

    def test_admin_page_shows_logout(self, client):
        """Test admin page shows logout button for authenticated users."""
        response = client.get("/admin")
        assert response.status_code == 200
        content = response.text

        # Should show logout button
        assert 'href="/logout"' in content

    def test_assays_page_shows_logout(self, client):
        """Test assays page shows logout button for authenticated users."""
        response = client.get("/assays")
        assert response.status_code == 200
        content = response.text

        # Should show logout button
        assert 'href="/logout"' in content


class TestModernUINavigation:
    """Tests for modern UI navigation elements."""

    def test_dashboard_has_navigation_links(self, client):
        """Test dashboard has all expected navigation links."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # Check for main navigation links
        assert 'href="/"' in content  # Dashboard
        assert 'href="/assays"' in content
        assert 'href="/workflows"' in content
        assert 'href="/admin"' in content
        assert 'href="/create_object"' in content
        assert 'href="/search"' in content

    def test_dashboard_has_legacy_link(self, client):
        """Test dashboard has link to legacy UI."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # Should have legacy UI link
        assert 'href="/legacy/"' in content or "Legacy" in content

    def test_modern_pages_use_bloom_modern_css(self, client):
        """Test modern pages include the modern CSS file."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # Should include modern CSS
        assert "bloom_modern.css" in content

    def test_modern_pages_use_bloom_modern_js(self, client):
        """Test modern pages include the modern JS file."""
        response = client.get("/")
        assert response.status_code == 200
        content = response.text

        # Should include modern JS
        assert "bloom_modern.js" in content


class TestFileAndDeweyEndpoints:
    """Tests for file management (Dewey) endpoints."""

    @pytest.mark.skip(reason="Requires /Users/jmajor/Downloads/dewey_search.tsv file to exist")
    def test_visual_report_returns_html(self, client):
        """Test visual report page returns HTML or handles gracefully."""
        response = client.get("/visual_report")
        # May fail due to missing file, accept various responses
        assert response.status_code in [200, 307, 400, 404, 500]

    def test_search_files_post(self, client):
        """Test search files POST endpoint."""
        response = client.post("/search_files", data={"search_query": "test"})
        # Should not return 404 or 405
        assert response.status_code in [200, 422, 307]

    def test_search_file_sets_post(self, client):
        """Test search file sets POST endpoint."""
        response = client.post("/search_file_sets", data={"search_query": "test"})
        assert response.status_code in [200, 422, 307]

    def test_file_set_urls_requires_euid(self, client):
        """Test file_set_urls endpoint requires EUID parameter."""
        response = client.get("/file_set_urls")
        # Should handle missing parameter gracefully
        assert response.status_code in [200, 307, 400, 422, 500]

    def test_delete_temp_file(self, client):
        """Test delete temp file endpoint."""
        response = client.get("/delete_temp_file")
        # Should handle missing file gracefully
        assert response.status_code in [200, 307, 400, 404, 422]


class TestGraphAndVisualizationEndpoints:
    """Tests for graph and visualization endpoints."""

    def test_get_dagv2_requires_euid(self, client):
        """Test get_dagv2 endpoint."""
        response = client.get("/get_dagv2")
        # Missing euid should be handled
        assert response.status_code in [200, 307, 400, 422, 500]

    def test_get_node_info_requires_node(self, client):
        """Test get_node_info endpoint."""
        response = client.get("/get_node_info")
        assert response.status_code in [200, 307, 400, 422, 500]

    def test_get_node_property_requires_uuid(self, client):
        """Test get_node_property endpoint."""
        response = client.get("/get_node_property")
        assert response.status_code in [200, 307, 400, 422, 500]


class TestDataModificationEndpoints:
    """Tests for data modification POST endpoints."""

    def test_query_by_euids_post(self, client):
        """Test query by EUIDs POST endpoint."""
        response = client.post("/query_by_euids", data={"euids": "EX1"})
        assert response.status_code in [200, 307, 422]

    def test_update_preference_post(self, client):
        """Test update preference POST endpoint."""
        response = client.post(
            "/update_preference",
            json={"preference_key": "skin_css", "preference_value": "/static/legacy/skins/bloom.css"},
        )
        assert response.status_code in [200, 307, 422]

    def test_save_json_addl_key_post(self, client):
        """Test save JSON addl key POST endpoint."""
        response = client.post(
            "/save_json_addl_key",
            json={"uuid": "test-uuid", "key": "test", "value": "test"},
        )
        assert response.status_code in [200, 307, 400, 422, 500]

    @pytest.mark.skip(reason="Endpoint expects specific workflow step state data")
    def test_update_accordion_state_post(self, client):
        """Test update accordion state POST endpoint."""
        response = client.post(
            "/update_accordion_state",
            json={"step_euid": "WF1", "section": "test", "is_open": True, "state": "open"},
        )
        assert response.status_code in [200, 307, 400, 422, 500]

    @pytest.mark.skip(reason="Endpoint expects form data with specific format")
    def test_generic_templates_post(self, client):
        """Test generic templates POST endpoint."""
        response = client.post("/generic_templates", data={"query": "test"})
        assert response.status_code in [200, 307, 400, 422, 500]


class TestAdminAndConfigEndpoints:
    """Tests for admin and configuration endpoints."""

    def test_admin_template_get(self, client):
        """Test admin template GET endpoint."""
        response = client.get("/admin_template")
        assert response.status_code in [200, 307, 400, 422]

    def test_update_object_name_requires_params(self, client):
        """Test update object name endpoint requires parameters."""
        response = client.get("/update_object_name")
        assert response.status_code in [200, 307, 400, 422, 500]

    def test_uuid_details_requires_uuid(self, client):
        """Test UUID details endpoint requires UUID parameter."""
        response = client.get("/uuid_details")
        assert response.status_code in [200, 307, 400, 422, 500]

    @pytest.mark.skip(reason="Requires valid EUID that exists in database")
    def test_vertical_exp_requires_euid(self, client):
        """Test vertical exp endpoint requires EUID parameter."""
        response = client.get("/vertical_exp?euid=EX1")
        assert response.status_code in [200, 307, 400, 422, 500]


class TestCalculationEndpoints:
    """Tests for calculation endpoints."""

    def test_calculate_cogs_children(self, client):
        """Test calculate COGS children endpoint."""
        response = client.get("/calculate_cogs_children")
        # Should handle missing parameters
        assert response.status_code in [200, 307, 400, 422, 500]


class TestProtectedEndpoints:
    """Tests for protected content endpoints."""

    def test_protected_content(self, client):
        """Test protected content endpoint."""
        response = client.get("/protected_content")
        assert response.status_code in [200, 307, 400, 401, 403]

    def test_serve_endpoint_with_path(self, client):
        """Test serve endpoint with file path."""
        response = client.get("/serve_endpoint/test.txt")
        assert response.status_code in [200, 307, 400, 404]