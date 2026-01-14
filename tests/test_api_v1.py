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

