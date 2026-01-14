"""
Tests for BLOOM LIMS Pydantic Schemas

These tests verify that the Pydantic schemas work correctly for
validation, serialization, and deserialization.
"""

import pytest
from datetime import datetime, date
from pydantic import ValidationError


class TestBaseSchemas:
    """Tests for base schema functionality."""
    
    def test_pagination_params(self):
        """Test PaginationParams schema."""
        from bloom_lims.schemas import PaginationParams
        
        params = PaginationParams(page=1, page_size=50)
        assert params.page == 1
        assert params.page_size == 50
        
        # Test defaults
        params_default = PaginationParams()
        assert params_default.page == 1
        assert params_default.page_size == 50
    
    def test_euid_validation(self):
        """Test EUID validation function.

        BLOOM EUIDs follow the pattern: PREFIX + SEQUENCE_NUMBER
        - PREFIX: 2-3 uppercase letters (e.g., CX, WX, MRX)
        - SEQUENCE_NUMBER: Integer with NO leading zeros

        Valid examples: CX1, CX123, WX1000, MRX42
        """
        from bloom_lims.schemas import validate_euid

        # Valid EUIDs (format: PREFIX + sequence number)
        assert validate_euid("CX1") == "CX1"
        assert validate_euid("CX123") == "CX123"
        assert validate_euid("  wx1000  ") == "WX1000"  # Should uppercase and strip
        assert validate_euid("MRX42") == "MRX42"

        # Invalid EUIDs
        with pytest.raises(ValueError):
            validate_euid("")
        with pytest.raises(ValueError):
            validate_euid("   ")
        with pytest.raises(ValueError):
            validate_euid("BLM-123456")  # Hyphens not allowed
        with pytest.raises(ValueError):
            validate_euid("CX01")  # Leading zeros not allowed


class TestObjectSchemas:
    """Tests for object schemas."""
    
    def test_object_create_schema(self):
        """Test ObjectCreateSchema validation."""
        from bloom_lims.schemas import ObjectCreateSchema
        
        data = ObjectCreateSchema(
            name="Test Object",
            btype="sample",
            b_sub_type="blood",
        )
        assert data.name == "Test Object"
        assert data.btype == "sample"
        assert data.b_sub_type == "blood"
    
    def test_object_create_with_json_addl(self):
        """Test ObjectCreateSchema with json_addl."""
        from bloom_lims.schemas import ObjectCreateSchema
        
        data = ObjectCreateSchema(
            name="Test Object",
            btype="sample",
            json_addl={"properties": {"key": "value"}},
        )
        assert data.json_addl == {"properties": {"key": "value"}}


class TestContainerSchemas:
    """Tests for container schemas."""
    
    def test_container_create_schema(self):
        """Test ContainerCreateSchema validation."""
        from bloom_lims.schemas import ContainerCreateSchema

        data = ContainerCreateSchema(
            name="Test Plate",
            container_type="plate",
            b_sub_type="96-well",
            template_euid="CT123456",  # Valid EUID format: PREFIX + sequence number
        )
        assert data.name == "Test Plate"
        assert data.container_type == "plate"
    
    def test_container_layout_schema(self):
        """Test ContainerLayoutSchema."""
        from bloom_lims.schemas import ContainerLayoutSchema
        
        layout = ContainerLayoutSchema(
            rows=8,
            columns=12,
            layout_type="grid",
        )
        assert layout.rows == 8
        assert layout.columns == 12


class TestContentSchemas:
    """Tests for content schemas."""
    
    def test_sample_create_schema(self):
        """Test SampleCreateSchema validation."""
        from bloom_lims.schemas import SampleCreateSchema
        
        data = SampleCreateSchema(
            name="Test Sample",
            sample_type="blood",
            template_euid="BLM123456",
        )
        assert data.name == "Test Sample"
        assert data.sample_type == "blood"
    
    def test_reagent_create_schema(self):
        """Test ReagentCreateSchema validation."""
        from bloom_lims.schemas import ReagentCreateSchema
        
        data = ReagentCreateSchema(
            name="Test Reagent",
            reagent_type="buffer",
            template_euid="BLM123456",
            lot_number="LOT001",
        )
        assert data.lot_number == "LOT001"


class TestWorkflowSchemas:
    """Tests for workflow schemas."""
    
    def test_workflow_create_schema(self):
        """Test WorkflowCreateSchema validation."""
        from bloom_lims.schemas import WorkflowCreateSchema

        data = WorkflowCreateSchema(
            name="Test Workflow",
            workflow_type="sequencing",
            template_euid="WF123456",  # Valid EUID format: PREFIX + sequence number
        )
        assert data.name == "Test Workflow"
    
    def test_workflow_step_schema(self):
        """Test WorkflowStepSchema validation."""
        from bloom_lims.schemas import WorkflowStepSchema
        
        step = WorkflowStepSchema(
            name="Step 1",
            step_number=1,
            step_type="extraction",
        )
        assert step.step_number == 1


class TestEquipmentSchemas:
    """Tests for equipment schemas."""
    
    def test_equipment_create_schema(self):
        """Test EquipmentCreateSchema validation."""
        from bloom_lims.schemas import EquipmentCreateSchema
        
        data = EquipmentCreateSchema(
            name="Test Sequencer",
            equipment_type="sequencer",
            serial_number="SN12345",
            manufacturer="Illumina",
        )
        assert data.serial_number == "SN12345"
    
    def test_maintenance_record_schema(self):
        """Test MaintenanceRecordSchema validation."""
        from bloom_lims.schemas import MaintenanceRecordSchema
        
        record = MaintenanceRecordSchema(
            maintenance_type="preventive",
            performed_date=datetime.now(),
            performed_by="Tech1",
        )
        assert record.maintenance_type == "preventive"

