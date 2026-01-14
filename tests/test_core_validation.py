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
    """Tests for validate_euid function.

    BLOOM EUIDs follow the pattern: PREFIX + SEQUENCE_NUMBER
    - PREFIX: 2-3 uppercase letters identifying object type (e.g., CX, WX, MRX)
    - SEQUENCE_NUMBER: Integer with NO leading zeros

    Valid examples: CX1, CX123, WX1000, MRX42, CWX5
    """

    def test_valid_euid(self):
        """Test validation of valid EUIDs."""
        # Format: 2-3 letter prefix + sequence number (no leading zeros)
        assert validate_euid("CX1") is True
        assert validate_euid("CX123") is True
        assert validate_euid("WX1000") is True
        assert validate_euid("MRX42") is True
        assert validate_euid("CWX5") is True

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

    def test_invalid_format_with_separator(self):
        """Test that EUID with separators (underscore/hyphen) raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid("WF-123")
        assert "PREFIX + sequence number" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            validate_euid("WF_123")
        assert "PREFIX + sequence number" in str(exc_info.value)

    def test_invalid_format_with_leading_zero(self):
        """Test that EUID with leading zero in sequence raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_euid("CX01")
        assert "No leading zeros" in str(exc_info.value)


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

        result = process("WX123")
        assert result == "processed: WX123"

    def test_invalid_argument_raises(self):
        """Test that invalid arguments raise ValidationError."""
        @validated(euid=validate_euid)
        def process(euid: str) -> str:
            return f"processed: {euid}"

        with pytest.raises(ValidationError):
            process("invalid-format")

    def test_multiple_validators(self):
        """Test multiple validators on different arguments."""
        @validated(euid=validate_euid, data=validate_json_addl)
        def process(euid: str, data: dict) -> dict:
            return {"euid": euid, "data": data}

        result = process("MRX42", {"key": "value"})
        assert result["euid"] == "MRX42"


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


# Template Validation Tests
from bloom_lims.core.template_validation import (
    TemplateValidator,
    ValidationResult,
    TemplateDefinition,
)
from pathlib import Path
import tempfile
import json


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = ValidationResult()
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.templates_checked == 0
        assert result.files_checked == 0

    def test_with_errors(self):
        """Test result with errors."""
        result = ValidationResult(
            valid=False,
            errors=["Error 1", "Error 2"],
            templates_checked=5,
        )
        assert result.valid is False
        assert len(result.errors) == 2


class TestTemplateDefinition:
    """Tests for TemplateDefinition dataclass."""

    def test_creation(self):
        """Test creating a template definition."""
        td = TemplateDefinition(
            file_path=Path("/test/template.json"),
            super_type="workflow",
            btype="dna_extraction",
            b_sub_type="dna_extraction_v1",
            version="1.0",
            data={"singleton": "0"},
        )
        assert td.super_type == "workflow"
        assert td.version == "1.0"
        assert td.action_imports == {}


class TestTemplateValidator:
    """Tests for TemplateValidator class."""

    def test_missing_config_directory(self):
        """Test validation with missing config directory."""
        validator = TemplateValidator(config_path=Path("/nonexistent/path"))
        result = validator.validate_all()

        assert result.valid is False
        assert "not found" in result.errors[0]

    def test_valid_reference_pattern(self):
        """Test reference pattern matching."""
        validator = TemplateValidator()

        # Valid patterns
        assert validator._is_valid_reference("action/generic/test/1.0")
        assert validator._is_valid_reference("workflow/dna_extraction/v1/1.0")
        assert validator._is_valid_reference("content/sample/blood/*/")

        # Invalid patterns
        assert not validator._is_valid_reference("invalid")
        assert not validator._is_valid_reference("no/slashes")

    def test_validate_with_temp_directory(self):
        """Test validation with temporary test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create subdirectory for super_type
            workflow_dir = tmppath / "workflow"
            workflow_dir.mkdir()

            # Create valid template file
            template_data = {
                "test_workflow": {
                    "1.0": {
                        "singleton": "0",
                        "action_imports": {
                            "default": {
                                "actions": {
                                    "action/generic/test/1.0": {}
                                }
                            }
                        }
                    }
                }
            }

            with open(workflow_dir / "test.json", "w") as f:
                json.dump(template_data, f)

            validator = TemplateValidator(config_path=tmppath)
            result = validator.validate_all()

            assert result.files_checked == 1
            assert result.templates_checked == 1

    def test_invalid_json(self):
        """Test handling of invalid JSON files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create invalid JSON file
            with open(tmppath / "invalid.json", "w") as f:
                f.write("{ invalid json }")

            validator = TemplateValidator(config_path=tmppath)
            result = validator.validate_all()

            assert result.valid is False
            assert any("Invalid JSON" in e for e in result.errors)

