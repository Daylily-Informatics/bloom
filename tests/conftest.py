"""
BLOOM LIMS Test Configuration and Fixtures

This module provides pytest fixtures and utilities for testing BLOOM LIMS.

Usage:
    # In test files, fixtures are automatically available
    def test_something(bdb, bloom_obj):
        result = bloom_obj.get_by_euid("WF_ABC123_X")
        assert result is not None

Fixtures:
    - bdb: Database connection (session-scoped)
    - bloom_obj: BloomObj instance
    - test_template: A test template for creating instances
    - clean_test_data: Cleanup fixture for test data
"""

import os
import pytest
import logging
from typing import Generator, Optional
from unittest.mock import MagicMock, patch

# Configure test logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# Environment setup for tests
def pytest_configure(config):
    """Configure pytest environment."""
    # Set test database port if not already set
    if "PGPORT" not in os.environ:
        os.environ["PGPORT"] = "5445"
    
    # Disable SQL echo during tests unless explicitly enabled
    if "ECHO_SQL" not in os.environ:
        os.environ["ECHO_SQL"] = "False"


@pytest.fixture(scope="session")
def bdb():
    """
    Session-scoped database connection fixture.
    
    Creates a single database connection for all tests in the session.
    The connection is automatically closed after all tests complete.
    
    Yields:
        BLOOMdb3: Database connection instance
    """
    from bloom_lims.db import BLOOMdb3
    
    logger.info("Creating test database connection")
    db = BLOOMdb3()
    
    yield db
    
    logger.info("Closing test database connection")
    db.close()


@pytest.fixture(scope="function")
def bdb_function():
    """
    Function-scoped database connection fixture.
    
    Creates a new database connection for each test function.
    Use this when tests need isolated database state.
    
    Yields:
        BLOOMdb3: Database connection instance
    """
    from bloom_lims.db import BLOOMdb3
    
    db = BLOOMdb3()
    yield db
    db.close()


@pytest.fixture(scope="function")
def bloom_obj(bdb):
    """
    BloomObj instance fixture.
    
    Creates a BloomObj instance using the session-scoped database connection.
    
    Args:
        bdb: Database connection fixture
        
    Yields:
        BloomObj: BloomObj instance
    """
    from bloom_lims.bobjs import BloomObj
    
    return BloomObj(bdb)


@pytest.fixture(scope="function")
def bloom_container(bdb):
    """BloomContainer instance fixture."""
    from bloom_lims.bobjs import BloomContainer
    return BloomContainer(bdb)


@pytest.fixture(scope="function")
def bloom_workflow(bdb):
    """BloomWorkflow instance fixture."""
    from bloom_lims.bobjs import BloomWorkflow
    return BloomWorkflow(bdb)


@pytest.fixture(scope="function")
def bloom_content(bdb):
    """BloomContent instance fixture."""
    from bloom_lims.bobjs import BloomContent
    return BloomContent(bdb)


@pytest.fixture(scope="function")
def test_template(bdb, bloom_obj):
    """
    Get a test template for creating instances.
    
    Returns the first available generic_template.
    
    Args:
        bdb: Database connection fixture
        bloom_obj: BloomObj fixture
        
    Returns:
        Template object or None if no templates exist
    """
    templates = bdb.session.query(bloom_obj.Base.classes.generic_template).limit(1).all()
    return templates[0] if templates else None


@pytest.fixture(scope="function")
def mock_session():
    """
    Mock SQLAlchemy session for unit tests.
    
    Use this when you want to test without database access.
    
    Returns:
        MagicMock: Mocked session object
    """
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter_by.return_value.first.return_value = None
    return session


@pytest.fixture(scope="function")
def clean_cache():
    """
    Clear the global cache before and after test.
    
    Use this when testing cache behavior.
    """
    from bloom_lims.core.cache import cache_clear
    
    cache_clear()
    yield
    cache_clear()


# Test markers
def pytest_collection_modifyitems(config, items):
    """Add markers to tests based on their location."""
    for item in items:
        # Mark integration tests
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        
        # Mark slow tests
        if "slow" in item.name.lower():
            item.add_marker(pytest.mark.slow)

