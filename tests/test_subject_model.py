"""
Tests for the Subject model and subjecting module.

Subjects are logical aggregates that decisions apply to, spanning multiple objects.
This test module validates:
- Subject creation and idempotency
- Anchor and member relationships
- Subject queries
- Action integration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSubjectKeyGeneration:
    """Tests for subject key generation."""

    def test_generate_subject_key_accession(self):
        """Test subject key generation for accession type."""
        from bloom_lims.subjecting import generate_subject_key
        
        key = generate_subject_key("accession", "CX123")
        assert key == "accession:CX123"

    def test_generate_subject_key_analysis_bundle(self):
        """Test subject key generation for analysis_bundle type."""
        from bloom_lims.subjecting import generate_subject_key
        
        key = generate_subject_key("analysis_bundle", "FX456")
        assert key == "analysis_bundle:FX456"

    def test_generate_subject_key_report(self):
        """Test subject key generation for report type."""
        from bloom_lims.subjecting import generate_subject_key
        
        key = generate_subject_key("report", "WX789")
        assert key == "report:WX789"

    def test_generate_subject_key_generic(self):
        """Test subject key generation for generic type."""
        from bloom_lims.subjecting import generate_subject_key
        
        key = generate_subject_key("generic", "EX100")
        assert key == "generic:EX100"


class TestSubjectTemplateMap:
    """Tests for subject template mapping."""

    def test_template_map_contains_expected_kinds(self):
        """Test that template map contains all expected subject kinds."""
        from bloom_lims.subjecting import SUBJECT_TEMPLATE_MAP
        
        expected_kinds = ["accession", "analysis_bundle", "report", "generic"]
        for kind in expected_kinds:
            assert kind in SUBJECT_TEMPLATE_MAP

    def test_template_paths_are_valid_format(self):
        """Test that template paths follow expected format."""
        from bloom_lims.subjecting import SUBJECT_TEMPLATE_MAP
        
        for kind, path in SUBJECT_TEMPLATE_MAP.items():
            parts = path.split("/")
            assert len(parts) == 4, f"Template path for {kind} should have 4 parts"
            assert parts[0] == "subject", f"Template path for {kind} should start with 'subject'"


class TestRelationshipConstants:
    """Tests for relationship type constants."""

    def test_relationship_constants_defined(self):
        """Test that relationship constants are properly defined."""
        from bloom_lims.subjecting import (
            RELATIONSHIP_SUBJECT_ANCHOR,
            RELATIONSHIP_SUBJECT_MEMBER,
        )
        
        assert RELATIONSHIP_SUBJECT_ANCHOR == "subject_anchor"
        assert RELATIONSHIP_SUBJECT_MEMBER == "subject_member"


class TestFindSubjectByKey:
    """Tests for find_subject_by_key function."""

    def test_find_subject_by_key_returns_none_when_not_found(self):
        """Test that find_subject_by_key returns None when subject not found."""
        from bloom_lims.subjecting import find_subject_by_key
        
        # Create mock bob with empty query results
        mock_bob = Mock()
        mock_bob.session.query.return_value.filter.return_value.all.return_value = []
        
        result = find_subject_by_key(mock_bob, "nonexistent:key")
        assert result is None

    def test_find_subject_by_key_returns_matching_subject(self):
        """Test that find_subject_by_key returns matching subject."""
        from bloom_lims.subjecting import find_subject_by_key
        
        # Create mock subject
        mock_subject = Mock()
        mock_subject.json_addl = {"properties": {"subject_key": "accession:CX123"}}
        mock_subject.super_type = "subject"
        mock_subject.is_deleted = False
        
        # Create mock bob
        mock_bob = Mock()
        mock_bob.session.query.return_value.filter.return_value.all.return_value = [mock_subject]
        
        result = find_subject_by_key(mock_bob, "accession:CX123")
        assert result == mock_subject


class TestListSubjectsForObject:
    """Tests for list_subjects_for_object function."""

    def test_list_subjects_for_object_returns_empty_when_no_subjects(self):
        """Test that list_subjects_for_object returns empty list when no subjects."""
        from bloom_lims.subjecting import list_subjects_for_object
        
        # Create mock object with no subject lineages
        mock_obj = Mock()
        mock_obj.child_of_lineages = []
        
        mock_bob = Mock()
        mock_bob.get_by_euid.return_value = mock_obj
        
        result = list_subjects_for_object(mock_bob, "CX123")
        assert result == []

    def test_list_subjects_for_object_returns_none_when_object_not_found(self):
        """Test that list_subjects_for_object returns empty list when object not found."""
        from bloom_lims.subjecting import list_subjects_for_object
        
        mock_bob = Mock()
        mock_bob.get_by_euid.return_value = None
        
        result = list_subjects_for_object(mock_bob, "NONEXISTENT")
        assert result == []


class TestListMembersForSubject:
    """Tests for list_members_for_subject function."""

    def test_list_members_for_subject_returns_empty_when_subject_not_found(self):
        """Test that list_members_for_subject returns empty dict when subject not found."""
        from bloom_lims.subjecting import list_members_for_subject
        
        mock_bob = Mock()
        mock_bob.get_by_euid.return_value = None
        
        result = list_members_for_subject(mock_bob, "NONEXISTENT")
        assert result == {"anchor": [], "members": []}

