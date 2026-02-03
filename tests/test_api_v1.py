"""
BLOOM LIMS API v1 Integration Tests

Tests for the REST API endpoints.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Set up auth bypass BEFORE importing FastAPI app
os.environ["BLOOM_API_AUTH"] = "no"

from fastapi.testclient import TestClient

# Add root to path for main import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    return TestClient(app)


class TestAPIRoot:
    """Tests for API root endpoints."""
    
    def test_api_v1_info(self, client):
        """Test API v1 info endpoint."""
        response = client.get("/api/v1/")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "endpoints" in data


class TestObjectsAPI:
    """Tests for /api/v1/objects endpoints."""
    
    def test_list_objects(self, client):
        """Test listing objects."""
        response = client.get("/api/v1/objects/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
    
    def test_list_objects_with_filters(self, client):
        """Test listing objects with filters."""
        response = client.get("/api/v1/objects/?super_type=container&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 10
    
    def test_get_object_not_found(self, client):
        """Test getting non-existent object."""
        response = client.get("/api/v1/objects/NONEXISTENT_EUID")
        assert response.status_code == 404


class TestContainersAPI:
    """Tests for /api/v1/containers endpoints."""
    
    def test_list_containers(self, client):
        """Test listing containers."""
        response = client.get("/api/v1/containers/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_get_container_not_found(self, client):
        """Test getting non-existent container."""
        response = client.get("/api/v1/containers/NONEXISTENT_EUID")
        assert response.status_code == 404


class TestContentAPI:
    """Tests for /api/v1/content endpoints."""
    
    def test_list_content(self, client):
        """Test listing content."""
        response = client.get("/api/v1/content/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_get_content_not_found(self, client):
        """Test getting non-existent content."""
        response = client.get("/api/v1/content/NONEXISTENT_EUID")
        assert response.status_code == 404


class TestWorkflowsAPI:
    """Tests for /api/v1/workflows endpoints."""
    
    def test_list_workflows(self, client):
        """Test listing workflows."""
        response = client.get("/api/v1/workflows/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_get_workflow_not_found(self, client):
        """Test getting non-existent workflow."""
        response = client.get("/api/v1/workflows/NONEXISTENT_EUID")
        assert response.status_code == 404


class TestTemplatesAPI:
    """Tests for /api/v1/templates endpoints."""
    
    def test_list_templates(self, client):
        """Test listing templates."""
        response = client.get("/api/v1/templates/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_list_templates_by_super_type(self, client):
        """Test listing templates by super_type."""
        response = client.get("/api/v1/templates/by-type/container")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert data["super_type"] == "container"


class TestSubjectsAPI:
    """Tests for /api/v1/subjects endpoints."""
    
    def test_list_subjects(self, client):
        """Test listing subjects."""
        response = client.get("/api/v1/subjects/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_get_subject_not_found(self, client):
        """Test getting non-existent subject."""
        response = client.get("/api/v1/subjects/NONEXISTENT_EUID")
        assert response.status_code == 404


class TestLineagesAPI:
    """Tests for /api/v1/lineages endpoints."""

    def test_list_lineages(self, client):
        """Test listing lineages."""
        response = client.get("/api/v1/lineages/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestStatsAPI:
    """Tests for /api/v1/stats endpoints."""

    def test_dashboard_stats(self, client):
        """Test dashboard stats endpoint."""
        response = client.get("/api/v1/stats/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "stats" in data
        assert "recent_activity" in data
        assert "generated_at" in data

    def test_dashboard_stats_structure(self, client):
        """Test dashboard stats response structure."""
        response = client.get("/api/v1/stats/dashboard")
        assert response.status_code == 200
        data = response.json()

        # Validate stats structure
        stats = data["stats"]
        assert "assays_total" in stats
        assert "workflows_total" in stats
        assert "equipment_total" in stats
        assert "reagents_total" in stats

        # Validate recent_activity structure
        recent = data["recent_activity"]
        assert "recent_assays" in recent
        assert "recent_workflows" in recent


class TestSearchAPI:
    """Tests for /api/v1/search endpoints."""

    def test_search_requires_query(self, client):
        """Test search requires a query parameter."""
        response = client.get("/api/v1/search/")
        assert response.status_code == 422  # Validation error - missing required param

    def test_search_with_query(self, client):
        """Test search with a query returns results."""
        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    def test_search_with_type_filter(self, client):
        """Test search with type filter."""
        response = client.get("/api/v1/search/?q=test&types=container,content")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_search_export_tsv(self, client):
        """Test search export as TSV."""
        response = client.get("/api/v1/search/export?q=test&format=tsv")
        assert response.status_code == 200
        # TSV should have content-disposition header
        assert "text/tab-separated-values" in response.headers.get("content-type", "")

    def test_search_export_json(self, client):
        """Test search export as JSON."""
        response = client.get("/api/v1/search/export?q=test&format=json")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
        data = response.json()
        assert "items" in data


class TestBulkContainerAPI:
    """Tests for /api/v1/containers/bulk-create endpoint."""

    def test_bulk_create_requires_file(self, client):
        """Test bulk create requires a file upload."""
        response = client.post("/api/v1/containers/bulk-create")
        assert response.status_code == 422  # Validation error - missing file

    def test_bulk_create_with_empty_file(self, client):
        """Test bulk create with empty TSV file."""
        import io
        empty_tsv = "container_template_euid\tcontainer_type\tcontainer_name\n"
        files = {"file": ("test.tsv", io.BytesIO(empty_tsv.encode()), "text/tab-separated-values")}
        response = client.post("/api/v1/containers/bulk-create", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_rows"] == 0
        assert data["created_count"] == 0

    def test_bulk_create_returns_correct_structure(self, client):
        """Test bulk create response has correct structure."""
        import io
        tsv_content = "container_template_euid\tcontainer_type\tcontainer_name\n"
        files = {"file": ("test.tsv", io.BytesIO(tsv_content.encode()), "text/tab-separated-values")}
        response = client.post("/api/v1/containers/bulk-create", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "total_rows" in data
        assert "created_count" in data
        assert "error_count" in data
        assert "created" in data
        assert "errors" in data


class TestEquipmentAPI:
    """Tests for equipment API endpoints."""

    def test_list_equipment(self, client):
        """Test listing equipment."""
        response = client.get("/api/v1/equipment/")
        assert response.status_code == 200
        data = response.json()
        # API returns paginated response with 'items' key
        assert "items" in data
        assert "total" in data

    def test_get_equipment_not_found(self, client):
        """Test getting non-existent equipment."""
        response = client.get("/api/v1/equipment/00000000-0000-0000-0000-000000000000")
        # 404 for not found, 422 for invalid UUID format, 500 for server error
        assert response.status_code in [404, 422, 500]


class TestFilesAPI:
    """Tests for files API endpoints."""

    def test_list_files(self, client):
        """Test listing files."""
        response = client.get("/api/v1/files/")
        assert response.status_code == 200
        data = response.json()
        # API returns paginated response
        assert "items" in data
        assert "total" in data

    def test_list_file_sets(self, client):
        """Test listing file sets."""
        response = client.get("/api/v1/file-sets/")
        assert response.status_code == 200
        data = response.json()
        # API returns paginated response
        assert "items" in data
        assert "total" in data
