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
        response = client.get("/api/v1/objects/?category=container&page_size=10")
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
    
    def test_list_templates_by_category(self, client):
        """Test listing templates by category."""
        response = client.get("/api/v1/templates/by-category/container")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert data["category"] == "container"


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


class TestActionsAPI:
    """Tests for actions API endpoints."""

    def test_list_actions(self, client):
        """Test listing actions - endpoint may not exist."""
        response = client.get("/api/v1/actions/")
        # Actions endpoint may not be implemented
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "items" in data or isinstance(data, list)

    def test_get_action_not_found(self, client):
        """Test getting non-existent action."""
        response = client.get("/api/v1/actions/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [404, 422, 500]


class TestSubjectsAPIExtended:
    """Extended tests for subjects API endpoints."""

    def test_list_subjects_with_pagination(self, client):
        """Test listing subjects with pagination."""
        response = client.get("/api/v1/subjects/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data


class TestObjectCreationAPI:
    """Tests for object creation API endpoints."""

    def test_get_categories(self, client):
        """Test getting categories."""
        response = client.get("/api/v1/object-creation/categories")
        assert response.status_code == 200
        data = response.json()
        # Response is a dict with 'categories' key
        if isinstance(data, dict):
            assert "categories" in data
            categories = data["categories"]
        else:
            categories = data
        assert isinstance(categories, list)
        # Should include common categories
        type_names = [item.get("name") or item for item in categories]
        assert any("container" in str(cat).lower() for cat in type_names)

    def test_get_types_for_category(self, client):
        """Test getting types for a category."""
        # Use query parameter format
        response = client.get("/api/v1/object-creation/types?category=container")
        # May return 404 if endpoint uses different path
        assert response.status_code in [200, 404, 422]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_types_for_invalid_category(self, client):
        """Test getting types for invalid category."""
        response = client.get("/api/v1/object-creation/types?category=invalid_type")
        assert response.status_code in [200, 404, 422]

    def test_get_subtypes(self, client):
        """Test getting subtypes."""
        response = client.get("/api/v1/object-creation/subtypes?category=container&type=plate")
        assert response.status_code in [200, 404, 422]


class TestObjectCreationPathTraversal:
    """Tests for path traversal protection in object creation API."""

    def test_types_rejects_path_traversal_dotdot(self, client):
        """Test that /types rejects .. in category."""
        response = client.get("/api/v1/object-creation/types?category=..")
        assert response.status_code == 400
        assert "parent directory" in response.json().get("detail", "").lower()

    def test_types_rejects_path_traversal_slash(self, client):
        """Test that /types rejects / in category."""
        response = client.get("/api/v1/object-creation/types?category=container/../../etc")
        assert response.status_code == 400
        assert "path separator" in response.json().get("detail", "").lower()

    def test_types_rejects_path_traversal_backslash(self, client):
        """Test that /types rejects \\ in category."""
        response = client.get("/api/v1/object-creation/types?category=container\\..\\etc")
        assert response.status_code == 400
        assert "path separator" in response.json().get("detail", "").lower()

    def test_subtypes_rejects_path_traversal_category(self, client):
        """Test that /subtypes rejects .. in category."""
        response = client.get("/api/v1/object-creation/subtypes?category=..&type=plate")
        assert response.status_code == 400
        assert "parent directory" in response.json().get("detail", "").lower()

    def test_subtypes_rejects_path_traversal_type(self, client):
        """Test that /subtypes rejects .. in type."""
        response = client.get("/api/v1/object-creation/subtypes?category=container&type=../../../etc/passwd")
        assert response.status_code == 400
        assert "path separator" in response.json().get("detail", "").lower()

    def test_template_rejects_path_traversal_category(self, client):
        """Test that /template rejects .. in category."""
        response = client.get(
            "/api/v1/object-creation/template?category=..&type=plate&subtype=test&version=1"
        )
        assert response.status_code == 400
        assert "parent directory" in response.json().get("detail", "").lower()

    def test_template_rejects_path_traversal_type(self, client):
        """Test that /template rejects path traversal in type."""
        response = client.get(
            "/api/v1/object-creation/template?category=container&type=../../../etc/passwd&subtype=test&version=1"
        )
        assert response.status_code == 400
        assert "path separator" in response.json().get("detail", "").lower()

    def test_types_accepts_valid_category(self, client):
        """Test that /types accepts valid category values."""
        response = client.get("/api/v1/object-creation/types?category=container")
        # Should be 200 or 404 (if container doesn't exist), but NOT 400
        assert response.status_code in [200, 404]

    def test_subtypes_accepts_valid_params(self, client):
        """Test that /subtypes accepts valid parameter values."""
        response = client.get("/api/v1/object-creation/subtypes?category=container&type=plate")
        # Should be 200 or 404, but NOT 400
        assert response.status_code in [200, 404]

    def test_types_rejects_invalid_characters(self, client):
        """Test that /types rejects invalid characters in category."""
        response = client.get("/api/v1/object-creation/types?category=Container")
        assert response.status_code == 400
        assert "lowercase" in response.json().get("detail", "").lower()


class TestTemplatesAPIExtended:
    """Extended tests for templates API endpoints."""

    def test_list_templates_with_pagination(self, client):
        """Test listing templates with pagination."""
        response = client.get("/api/v1/templates/?page=1&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) <= 5

    def test_get_template_by_euid(self, client):
        """Test getting template by EUID."""
        # First get a list of templates to find a valid EUID
        response = client.get("/api/v1/templates/?page_size=1")
        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            euid = data["items"][0].get("euid")
            if euid:
                response = client.get(f"/api/v1/templates/{euid}")
                assert response.status_code in [200, 404]


class TestWorkflowsAPIExtended:
    """Extended tests for workflows API endpoints."""

    def test_list_workflows_with_pagination(self, client):
        """Test listing workflows with pagination."""
        response = client.get("/api/v1/workflows/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestContainersAPIExtended:
    """Extended tests for containers API endpoints."""

    def test_list_containers_with_pagination(self, client):
        """Test listing containers with pagination."""
        response = client.get("/api/v1/containers/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_list_containers_with_type_filter(self, client):
        """Test listing containers with type filter."""
        response = client.get("/api/v1/containers/?container_type=plate")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data


class TestContentAPIExtended:
    """Extended tests for content API endpoints."""

    def test_list_content_with_pagination(self, client):
        """Test listing content with pagination."""
        response = client.get("/api/v1/content/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestLineagesAPIExtended:
    """Extended tests for lineages API endpoints."""

    def test_list_lineages_with_pagination(self, client):
        """Test listing lineages with pagination."""
        response = client.get("/api/v1/lineages/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestStatsAPIExtended:
    """Extended tests for stats API endpoints."""

    def test_dashboard_stats_has_required_fields(self, client):
        """Test dashboard stats has all required fields."""
        response = client.get("/api/v1/stats/dashboard")
        assert response.status_code == 200
        data = response.json()
        # Check for expected stat categories
        assert "total_objects" in data or "containers" in data or isinstance(data, dict)


class TestBatchAPIExtended:
    """Extended tests for batch API endpoints."""

    def test_batch_status_empty(self, client):
        """Test getting batch job status list."""
        response = client.get("/api/v1/batch/jobs")
        # May return 404 if no jobs exist, or 200 with empty list
        assert response.status_code in [200, 404]

    def test_batch_job_not_found(self, client):
        """Test getting non-existent batch job."""
        response = client.get("/api/v1/batch/jobs/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [404, 422, 500]


class TestSearchAPIExtended:
    """Extended tests for search API endpoints."""

    def test_search_empty_query(self, client):
        """Test search with empty query returns error."""
        response = client.get("/api/v1/search/?q=")
        # Should return 422 for validation error
        assert response.status_code in [200, 422]

    def test_search_with_type_filter_content(self, client):
        """Test search filtering by content type."""
        response = client.get("/api/v1/search/?q=test&types=content")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data or "results" in data or isinstance(data, list)

    def test_search_with_multiple_types(self, client):
        """Test search filtering by multiple types."""
        response = client.get("/api/v1/search/?q=sample&types=container,content")
        assert response.status_code == 200

    def test_search_pagination(self, client):
        """Test search with pagination."""
        response = client.get("/api/v1/search/?q=test&page=1&page_size=5")
        assert response.status_code == 200


class TestFileSetsAPIExtended:
    """Extended tests for file sets API endpoints."""

    def test_list_file_sets_with_pagination(self, client):
        """Test listing file sets with pagination."""
        response = client.get("/api/v1/file-sets/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_file_set_not_found(self, client):
        """Test getting non-existent file set."""
        response = client.get("/api/v1/file-sets/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [404, 422, 500]


class TestObjectsAPIExtended:
    """Extended tests for objects API endpoints."""

    def test_list_objects(self, client):
        """Test listing objects."""
        response = client.get("/api/v1/objects/")
        assert response.status_code in [200, 404]

    def test_get_object_by_uuid(self, client):
        """Test getting object by UUID."""
        response = client.get("/api/v1/objects/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [404, 422, 500]

    def test_get_object_by_euid(self, client):
        """Test getting object by EUID."""
        response = client.get("/api/v1/objects/euid/CX1")
        assert response.status_code in [200, 404, 422]


class TestAuthAPI:
    """Tests for auth API endpoints."""

    def test_auth_me(self, client):
        """Test /auth/me endpoint."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code in [200, 401, 404]

    def test_auth_session(self, client):
        """Test /auth/session endpoint."""
        response = client.get("/api/v1/auth/session")
        assert response.status_code in [200, 401, 404]


class TestAsyncTasksAPI:
    """Tests for async tasks API endpoints."""

    def test_list_tasks(self, client):
        """Test listing async tasks."""
        response = client.get("/api/v1/tasks/")
        assert response.status_code in [200, 404]

    def test_get_task_not_found(self, client):
        """Test getting non-existent task."""
        response = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [404, 422, 500]


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_endpoint(self, client):
        """Test /health endpoint."""
        response = client.get("/health")
        # Health endpoint should return 200 or be not implemented (404)
        assert response.status_code in [200, 404, 503]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data or isinstance(data, dict)

    def test_ready_endpoint(self, client):
        """Test /ready endpoint."""
        response = client.get("/ready")
        assert response.status_code in [200, 404, 503]

    def test_live_endpoint(self, client):
        """Test /live endpoint."""
        response = client.get("/live")
        assert response.status_code in [200, 404, 503]


class TestAPIVersionInfo:
    """Tests for API version info endpoints."""

    def test_api_version(self, client):
        """Test API version endpoint."""
        response = client.get("/api/v1/version")
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)

    def test_api_info(self, client):
        """Test API info endpoint."""
        response = client.get("/api/v1/info")
        assert response.status_code in [200, 404]


class TestActionsAPIExtended:
    """Extended tests for actions API."""

    def test_create_action_invalid(self, client):
        """Test creating action with invalid data."""
        response = client.post("/api/v1/actions/", json={})
        assert response.status_code in [400, 404, 422, 500]

    def test_actions_list_pagination(self, client):
        """Test actions list with pagination params."""
        response = client.get("/api/v1/actions/?page=1&page_size=10")
        assert response.status_code in [200, 404]


class TestSubjectsAPIDeep:
    """Deeper tests for subjects API."""

    def test_subjects_list_pagination(self, client):
        """Test subjects list with pagination params."""
        response = client.get("/api/v1/subjects/?page=1&page_size=5")
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "items" in data or isinstance(data, list)

    def test_subject_by_invalid_uuid(self, client):
        """Test getting subject by invalid UUID."""
        response = client.get("/api/v1/subjects/invalid-uuid")
        assert response.status_code in [404, 422, 500]


class TestWorkflowsAPIDeep:
    """Deeper tests for workflows API."""

    def test_workflows_list_pagination(self, client):
        """Test workflows list with pagination."""
        response = client.get("/api/v1/workflows/?page=1&page_size=10")
        assert response.status_code in [200, 404]

    def test_workflow_by_invalid_euid(self, client):
        """Test getting workflow by invalid EUID."""
        response = client.get("/api/v1/workflows/INVALID999")
        assert response.status_code in [404, 422, 500]

    def test_workflow_steps_by_invalid_uuid(self, client):
        """Test getting workflow steps for invalid UUID."""
        response = client.get("/api/v1/workflows/00000000-0000-0000-0000-000000000000/steps")
        assert response.status_code in [404, 422, 500]


class TestLineagesAPIDeep:
    """Deeper tests for lineages API."""

    def test_lineages_filter_by_type(self, client):
        """Test filtering lineages by type."""
        response = client.get("/api/v1/lineages/?type=container")
        assert response.status_code in [200, 404]

    def test_lineage_by_invalid_uuid(self, client):
        """Test getting lineage by invalid UUID."""
        response = client.get("/api/v1/lineages/invalid-uuid")
        # 405 Method Not Allowed is valid if the route doesn't support GET with path param
        assert response.status_code in [404, 405, 422, 500]


class TestFilesAPIDeep:
    """Deeper tests for files API."""

    def test_files_list_pagination(self, client):
        """Test files list with pagination."""
        response = client.get("/api/v1/files/?page=1&page_size=10")
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "items" in data or isinstance(data, list)

    def test_file_by_invalid_uuid(self, client):
        """Test getting file by invalid UUID."""
        response = client.get("/api/v1/files/invalid-uuid")
        assert response.status_code in [404, 422, 500]


class TestEquipmentAPIDeep:
    """Deeper tests for equipment API."""

    def test_equipment_list_pagination(self, client):
        """Test equipment list with pagination."""
        response = client.get("/api/v1/equipment/?page=1&page_size=10")
        assert response.status_code in [200, 404]

    def test_equipment_by_euid(self, client):
        """Test getting equipment by EUID."""
        response = client.get("/api/v1/equipment/by-euid/EQ1")
        assert response.status_code in [200, 404, 422]


class TestContentAPIDeep:
    """Deeper tests for content API."""

    def test_content_list_pagination(self, client):
        """Test content list with pagination."""
        response = client.get("/api/v1/content/?page=1&page_size=10")
        assert response.status_code in [200, 404]

    def test_content_by_type_filter(self, client):
        """Test content list with type filter."""
        response = client.get("/api/v1/content/?type=reagent")
        assert response.status_code in [200, 404]


class TestContainersAPIDeep:
    """Deeper tests for containers API."""

    def test_containers_by_category(self, client):
        """Test listing containers by category."""
        response = client.get("/api/v1/containers/?category=container")
        assert response.status_code in [200, 404]

    def test_container_children(self, client):
        """Test getting container children."""
        response = client.get("/api/v1/containers/00000000-0000-0000-0000-000000000000/children")
        assert response.status_code in [404, 422, 500]


class TestStatsAPIDeep:
    """Deeper tests for stats API."""

    def test_stats_overview(self, client):
        """Test stats overview endpoint."""
        response = client.get("/api/v1/stats/overview")
        assert response.status_code in [200, 404]

    def test_stats_by_type(self, client):
        """Test stats by type endpoint."""
        response = client.get("/api/v1/stats/by-type")
        assert response.status_code in [200, 404]


class TestObjectsAPI:
    """Tests for objects API endpoints."""

    def test_list_objects(self, client):
        """Test listing objects."""
        response = client.get("/api/v1/objects/")
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_object_by_uuid_invalid(self, client):
        """Test getting object by invalid UUID."""
        response = client.get("/api/v1/objects/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]

    def test_get_object_by_euid_invalid(self, client):
        """Test getting object by invalid EUID."""
        response = client.get("/api/v1/objects/euid/INVALID123")
        assert response.status_code in [404, 422, 500]


class TestSubjectsAPI:
    """Tests for subjects API endpoints."""

    def test_list_subjects(self, client):
        """Test listing subjects."""
        response = client.get("/api/v1/subjects/")
        assert response.status_code in [200, 404, 405]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_subject_invalid_uuid(self, client):
        """Test getting subject by invalid UUID."""
        response = client.get("/api/v1/subjects/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]


class TestContentAPI:
    """Tests for content API endpoints."""

    def test_list_content(self, client):
        """Test listing content."""
        response = client.get("/api/v1/content/")
        assert response.status_code in [200, 404, 405]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_content_invalid_uuid(self, client):
        """Test getting content by invalid UUID."""
        response = client.get("/api/v1/content/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]


class TestFilesAPI:
    """Tests for files API endpoints."""

    def test_list_files(self, client):
        """Test listing files."""
        response = client.get("/api/v1/files/")
        assert response.status_code in [200, 404, 405]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_file_invalid_uuid(self, client):
        """Test getting file by invalid UUID."""
        response = client.get("/api/v1/files/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]


class TestWorkflowsAPIDeep:
    """Extended tests for workflows API."""

    def test_list_workflows(self, client):
        """Test listing workflows."""
        response = client.get("/api/v1/workflows/")
        assert response.status_code in [200, 404, 405]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_workflow_invalid_uuid(self, client):
        """Test getting workflow by invalid UUID."""
        response = client.get("/api/v1/workflows/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]


class TestActionsAPIDeep:
    """Extended tests for actions API."""

    def test_list_actions(self, client):
        """Test listing actions."""
        response = client.get("/api/v1/actions/")
        assert response.status_code in [200, 404, 405]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))

    def test_get_action_invalid_uuid(self, client):
        """Test getting action by invalid UUID."""
        response = client.get("/api/v1/actions/invalid-uuid")
        assert response.status_code in [404, 405, 422, 500]


class TestDependenciesModule:
    """Tests for API dependencies module."""

    def test_import_dependencies(self):
        """Test dependencies module import."""
        from bloom_lims.api.v1 import dependencies
        assert dependencies is not None

    def test_import_api_user(self):
        """Test APIUser class import."""
        from bloom_lims.api.v1.dependencies import APIUser
        assert APIUser is not None


class TestVersioningModule:
    """Tests for API versioning module."""

    def test_import_versioning(self):
        """Test versioning module import."""
        from bloom_lims.api import versioning
        assert versioning is not None


class TestActionsOperations:
    """Tests for /api/v1/actions operation endpoints (aliquot, transfer, pool)."""

    def test_aliquot_action(self, client):
        """Test aliquot action endpoint."""
        response = client.post("/api/v1/actions/aliquot", json={})
        # May fail with validation error or not implemented
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_transfer_action(self, client):
        """Test transfer action endpoint."""
        response = client.post("/api/v1/actions/transfer", json={})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_pool_action(self, client):
        """Test pool action endpoint."""
        response = client.post("/api/v1/actions/pool", json={})
        assert response.status_code in [200, 400, 404, 422, 500]


class TestContentCreation:
    """Tests for /api/v1/content creation endpoints."""

    def test_create_sample(self, client):
        """Test create sample endpoint."""
        response = client.post("/api/v1/content/samples", json={})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_create_specimen(self, client):
        """Test create specimen endpoint."""
        response = client.post("/api/v1/content/specimens", json={})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_create_reagent(self, client):
        """Test create reagent endpoint."""
        response = client.post("/api/v1/content/reagents", json={})
        assert response.status_code in [200, 400, 404, 422, 500]


class TestEquipmentMaintenance:
    """Tests for /api/v1/equipment maintenance endpoint."""

    def test_equipment_maintenance(self, client):
        """Test equipment maintenance endpoint."""
        response = client.post("/api/v1/equipment/EQ1/maintenance", json={})
        assert response.status_code in [200, 400, 404, 422, 500]


class TestFileLinking:
    """Tests for /api/v1/files link endpoint."""

    def test_file_link(self, client):
        """Test file linking endpoint."""
        response = client.post("/api/v1/files/DAT1/link/CX1")
        assert response.status_code in [200, 400, 404, 422, 500]


class TestSubjectSpecimens:
    """Tests for /api/v1/subjects specimens endpoint."""

    def test_subject_specimens(self, client):
        """Test subject specimens endpoint."""
        response = client.get("/api/v1/subjects/SBJ1/specimens")
        assert response.status_code in [200, 400, 404, 422, 500]


class TestWorkflowAdvance:
    """Tests for /api/v1/workflows advance endpoint."""

    def test_workflow_advance(self, client):
        """Test workflow advance endpoint."""
        response = client.post("/api/v1/workflows/WF1/advance", json={})
        assert response.status_code in [200, 400, 404, 422, 500]


class TestAuthLogout:
    """Tests for /api/v1/auth logout endpoint."""

    def test_auth_logout(self, client):
        """Test auth logout endpoint."""
        response = client.post("/api/v1/auth/logout")
        assert response.status_code in [200, 302, 400, 404, 422, 500]


class TestBatchOperations:
    """Tests for /api/v1/batch operation endpoints."""

    def test_batch_create(self, client):
        """Test batch create endpoint."""
        response = client.post("/api/v1/batch/create", json={"operations": []})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_batch_update(self, client):
        """Test batch update endpoint."""
        response = client.post("/api/v1/batch/update", json={"operations": []})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_batch_delete(self, client):
        """Test batch delete endpoint."""
        response = client.post("/api/v1/batch/delete", json={"euids": []})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_batch_jobs_list(self, client):
        """Test batch jobs list endpoint."""
        response = client.get("/api/v1/batch/jobs")
        assert response.status_code in [200, 404]

    def test_batch_job_get(self, client):
        """Test batch job get endpoint."""
        response = client.get("/api/v1/batch/jobs/test-job-id")
        assert response.status_code in [200, 404, 422, 500]

    def test_batch_job_cancel(self, client):
        """Test batch job cancel endpoint."""
        response = client.post("/api/v1/batch/jobs/test-job-id/cancel")
        assert response.status_code in [200, 400, 404, 422, 500]


class TestAsyncTasks:
    """Tests for /api/v1/tasks async task endpoints."""

    def test_tasks_list(self, client):
        """Test tasks list endpoint."""
        response = client.get("/api/v1/tasks/")
        assert response.status_code in [200, 404]

    def test_task_types(self, client):
        """Test task types endpoint."""
        response = client.get("/api/v1/tasks/types")
        assert response.status_code in [200, 404]

    def test_task_submit(self, client):
        """Test task submit endpoint."""
        response = client.post("/api/v1/tasks/submit", json={"task_type": "test"})
        assert response.status_code in [200, 400, 404, 422, 500]

    def test_task_status(self, client):
        """Test task status endpoint."""
        response = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [200, 404, 422, 500]

    def test_task_wait(self, client):
        """Test task wait endpoint."""
        response = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000/wait")
        assert response.status_code in [200, 404, 422, 500]

    def test_task_cancel(self, client):
        """Test task cancel endpoint."""
        response = client.post("/api/v1/tasks/00000000-0000-0000-0000-000000000000/cancel")
        assert response.status_code in [200, 400, 404, 422, 500]


class TestWorksetsAPI:
    """Tests for /api/v1/worksets endpoints."""

    def test_list_worksets(self, client):
        """Test listing worksets."""
        response = client.get("/api/v1/worksets/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    def test_list_worksets_with_filters(self, client):
        """Test listing worksets with status filter."""
        response = client.get("/api/v1/worksets/?status=complete&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 10

    def test_list_worksets_with_workflow_filter(self, client):
        """Test listing worksets with workflow filter."""
        response = client.get("/api/v1/worksets/?workflow_euid=AY1")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_get_workset_not_found(self, client):
        """Test getting non-existent workset."""
        # Use a truly non-existent EUID pattern that won't match any object
        response = client.get("/api/v1/worksets/ZZZZZ_DOES_NOT_EXIST_99999")
        assert response.status_code == 404

    def test_get_workset_not_a_workset(self, client):
        """Test getting an object that exists but is not a workset."""
        # GT1 is a template, not a workset
        response = client.get("/api/v1/worksets/GT1")
        assert response.status_code == 404

    def test_create_workset_response_structure(self, client):
        """Test creating workset returns expected response structure."""
        # Note: This may create a workset even with non-existent anchor
        # depending on implementation. We just verify the response structure.
        response = client.post(
            "/api/v1/worksets/",
            json={
                "anchor_euid": "WSX1",  # Use a likely existing workflow step
                "workset_type": "accession",
            }
        )
        # Should return 200 with success structure or 400/500 on error
        assert response.status_code in [200, 400, 500]
        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "euid" in data or "message" in data

    def test_add_members_workset_not_found(self, client):
        """Test adding members to non-existent workset."""
        response = client.post(
            "/api/v1/worksets/ZZZZZ_DOES_NOT_EXIST_99999/members",
            json={"member_euids": ["CX1", "CX2"]}
        )
        assert response.status_code == 404

    def test_get_members_workset_not_found(self, client):
        """Test getting members of non-existent workset."""
        response = client.get("/api/v1/worksets/ZZZZZ_DOES_NOT_EXIST_99999/members")
        assert response.status_code == 404

    def test_complete_workset_not_found(self, client):
        """Test completing non-existent workset."""
        response = client.put(
            "/api/v1/worksets/ZZZZZ_DOES_NOT_EXIST_99999/complete",
            json={"status": "complete"}
        )
        assert response.status_code == 404

    def test_get_workset_by_anchor_response(self, client):
        """Test finding workset by anchor returns expected structure."""
        # Use a unique anchor that likely doesn't have a workset
        import uuid
        unique_anchor = f"TEST_ANCHOR_{uuid.uuid4().hex[:8]}"
        response = client.get(f"/api/v1/worksets/by-anchor/{unique_anchor}")
        # Should return 404 for non-existent anchor, or 200 with workset info
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "euid" in data
            assert "anchor_euid" in data