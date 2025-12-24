"""
Tests for bloom_lims.core.validation module.
"""

import pytest
import uuid

from bloom_lims.core.validation import (
    ValidationError,
    validate_euid,
    validate_uuid,
    validate_json_addl,
    validate_btype,
    validate_not_empty,
    validate_positive_int,
    validated,
    validate_schema,
)


class TestValidateEuid:
    """Tests for validate_euid function."""
    
    def test_valid_euid(self):
        """Test validation of valid EUIDs."""
        assert validate_euid("WF_ABC123_X") is True
        assert validate_euid("CT_SAMPLE01_Y") is True
        assert validate_euid("EQ_DEVICE_Z") is True
    
    def test_none_euid(self):
        """Test that None raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid(None)
        assert "cannot be None" in str(exc_info.value)
    
    def test_empty_euid(self):
        """Test that empty string raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid("")
        assert "cannot be empty" in str(exc_info.value)
    
    def test_non_string_euid(self):
        """Test that non-string raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid(12345)
        assert "must be a string" in str(exc_info.value)
    
    def test_no_underscore(self):
        """Test that EUID without underscore raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid("WFABC123X")
        assert "underscore" in str(exc_info.value)
    
    def test_lowercase_prefix(self):
        """Test that lowercase prefix raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid("wf_ABC123_X")
        assert "uppercase" in str(exc_info.value)


class TestValidateUuid:
    """Tests for validate_uuid function."""
    
    def test_valid_uuid_string(self):
        """Test validation of valid UUID string."""
        valid_uuid = str(uuid.uuid4())
        assert validate_uuid(valid_uuid) is True
    
    def test_valid_uuid_object(self):
        """Test validation of UUID object."""
        valid_uuid = uuid.uuid4()
        assert validate_uuid(valid_uuid) is True
    
    def test_none_uuid(self):
        """Test that None raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid(None)
        assert "cannot be None" in str(exc_info.value)
    
    def test_invalid_uuid_format(self):
        """Test that invalid format raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid("not-a-uuid")
        assert "Invalid UUID format" in str(exc_info.value)


class TestValidateJsonAddl:
    """Tests for validate_json_addl function."""
    
    def test_valid_dict(self):
        """Test validation of valid dict."""
        assert validate_json_addl({"key": "value"}) is True
    
    def test_none_allowed(self):
        """Test that None is allowed."""
        assert validate_json_addl(None) is True
    
    def test_non_dict(self):
        """Test that non-dict raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_json_addl("not a dict")
        assert "must be a dict" in str(exc_info.value)


class TestValidatedDecorator:
    """Tests for @validated decorator."""
    
    def test_valid_arguments(self):
        """Test that valid arguments pass through."""
        @validated(euid=validate_euid)
        def process(euid: str) -> str:
            return f"processed: {euid}"
        
        result = process("WF_ABC123_X")
        assert result == "processed: WF_ABC123_X"
    
    def test_invalid_argument_raises(self):
        """Test that invalid arguments raise ValidationError."""
        @validated(euid=validate_euid)
        def process(euid: str) -> str:
            return f"processed: {euid}"
        
        with pytest.raises(ValidationError):
            process("invalid")
    
    def test_multiple_validators(self):
        """Test multiple validators on different arguments."""
        @validated(euid=validate_euid, data=validate_json_addl)
        def process(euid: str, data: dict) -> dict:
            return {"euid": euid, "data": data}
        
        result = process("WF_ABC123_X", {"key": "value"})
        assert result["euid"] == "WF_ABC123_X"


class TestValidateSchema:
    """Tests for validate_schema function."""
    
    def test_valid_data(self):
        """Test validation of valid data against schema."""
        schema = {
            "name": {"type": str, "required": True},
            "count": {"type": int, "required": False},
        }
        data = {"name": "test", "count": 5}
        
        errors = validate_schema(data, schema)
        assert len(errors) == 0
    
    def test_missing_required_field(self):
        """Test that missing required field returns error."""
        schema = {
            "name": {"type": str, "required": True},
        }
        data = {}
        
        errors = validate_schema(data, schema)
        assert len(errors) == 1
        assert errors[0].field == "name"
    
    def test_wrong_type(self):
        """Test that wrong type returns error."""
        schema = {
            "count": {"type": int, "required": True},
        }
        data = {"count": "not an int"}
        
        errors = validate_schema(data, schema)
        assert len(errors) == 1
        assert "Expected int" in errors[0].message

