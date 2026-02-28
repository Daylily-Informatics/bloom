"""
Tests for biospecimen support in Bloom.

Tests verify:
1. Pydantic schema validation for API input/output
2. Specimen template instantiation via BloomContent.create_empty_content()
3. json_addl properties are populated from templates
4. Status and Atlas reference EUIDs can be stored in json_addl
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from bloom_lims.schemas.biospecimen import (
    BioSpecimenCreate,
    BioSpecimenUpdate,
    BioSpecimenStatusUpdate,
    BioSpecimenStatus,
    BioSpecimenResponse,
)


# ---------------------------------------------------------------------------
# Schema validation tests (no DB required)
# ---------------------------------------------------------------------------


class TestBioSpecimenSchemas:
    """Test Pydantic schemas for biospecimen API validation."""

    def test_create_schema_minimal(self):
        schema = BioSpecimenCreate(specimen_subtype="blood-whole")
        assert schema.specimen_subtype == "blood-whole"
        assert schema.specimen_barcode is None

    def test_create_schema_full(self):
        schema = BioSpecimenCreate(
            specimen_subtype="FFPE-Block",
            specimen_barcode="BC-12345",
            collection_date=datetime(2026, 1, 15),
            condition="good",
            volume="10",
            volume_units="mL",
            atlas_patient_euid="PT1",
            atlas_order_euid="OR1",
            comments="test specimen",
            lab_code="LAB1",
        )
        assert schema.specimen_subtype == "ffpe-block"  # normalized to lower
        assert schema.atlas_patient_euid == "PT1"

    def test_create_schema_normalizes_subtype(self):
        schema = BioSpecimenCreate(specimen_subtype="  Blood-Whole  ")
        assert schema.specimen_subtype == "blood-whole"

    def test_create_schema_validates_atlas_euids(self):
        with pytest.raises(ValidationError):
            BioSpecimenCreate(
                specimen_subtype="saliva",
                atlas_patient_euid="bad-euid-format",
            )

    def test_status_enum_values(self):
        assert BioSpecimenStatus.REGISTERED == "REGISTERED"
        assert BioSpecimenStatus.IN_TRANSIT == "IN_TRANSIT"
        assert BioSpecimenStatus.RECEIVED == "RECEIVED"
        assert BioSpecimenStatus.IN_PROCESS == "IN_PROCESS"
        assert BioSpecimenStatus.COMPLETE == "COMPLETE"
        assert BioSpecimenStatus.FAILED == "FAILED"
        assert BioSpecimenStatus.REJECTED == "REJECTED"
        assert len(BioSpecimenStatus) == 7

    def test_status_update_schema(self):
        update = BioSpecimenStatusUpdate(status=BioSpecimenStatus.RECEIVED)
        assert update.status == BioSpecimenStatus.RECEIVED

    def test_status_update_rejects_invalid(self):
        with pytest.raises(ValidationError):
            BioSpecimenStatusUpdate(status="INVALID_STATUS")

    def test_update_schema_partial(self):
        update = BioSpecimenUpdate(condition="good", volume="5")
        assert update.condition == "good"
        assert update.volume == "5"
        assert update.specimen_barcode is None

    def test_response_schema(self):
        resp = BioSpecimenResponse(
            euid="GI1",
            uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            name="Whole Blood",
            subtype="blood-whole",
            status="REGISTERED",
            properties={"name": "Whole Blood", "status": "REGISTERED"},
            is_deleted=False,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        assert resp.euid == "GI1"
        assert resp.status == "REGISTERED"


# ---------------------------------------------------------------------------
# Integration tests: specimen template instantiation (requires seeded DB)
# ---------------------------------------------------------------------------

SPECIMEN_SUBTYPES = ["blood-whole", "ffpe-block", "ffpe-slice", "saliva", "buccal-swab"]


def _db_available():
    """Check whether the Bloom database is reachable."""
    try:
        from bloom_lims.db import BLOOMdb3

        db = BLOOMdb3()
        db.session.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


_skip_no_db = pytest.mark.skipif(
    not _db_available(), reason="Bloom database not available"
)


@_skip_no_db
class TestBioSpecimenTemplateInstantiation:
    """Test creating specimen instances from JSON templates via BloomContent."""

    def test_specimen_templates_exist(self, bloom_obj):
        """All specimen subtypes should have seeded templates."""
        for subtype in SPECIMEN_SUBTYPES:
            templates = bloom_obj.query_template_by_component_v2(
                "content", "specimen", subtype, "1.0"
            )
            assert len(templates) >= 1, f"No template for content/specimen/{subtype}/1.0"

    def test_create_specimen_instance(self, bloom_content):
        """Create a specimen instance and verify properties from template."""
        templates = bloom_content.query_template_by_component_v2(
            "content", "specimen", "blood-whole", "1.0"
        )
        assert templates, "blood-whole template not found"

        result = bloom_content.create_empty_content(templates[0].euid)
        instance = result[0][0]

        assert instance is not None
        assert instance.type == "specimen"
        assert instance.subtype == "blood-whole"
        assert instance.category == "content"

        props = instance.json_addl.get("properties", {})
        assert "status" in props
        assert props["status"] == "REGISTERED"
        assert "specimen_barcode" in props
        assert "atlas_patient_euid" in props
        assert "collection_date" in props

    def test_update_status_in_json_addl(self, bloom_content):
        """Status can be updated in json_addl properties."""
        from sqlalchemy.orm.attributes import flag_modified

        templates = bloom_content.query_template_by_component_v2(
            "content", "specimen", "saliva", "1.0"
        )
        assert templates, "saliva template not found"

        result = bloom_content.create_empty_content(templates[0].euid)
        instance = result[0][0]
        assert instance.json_addl["properties"]["status"] == "REGISTERED"

        instance.json_addl["properties"]["status"] = "RECEIVED"
        flag_modified(instance, "json_addl")
        bloom_content.session.commit()

        refreshed = bloom_content.get_by_euid(instance.euid)
        assert refreshed.json_addl["properties"]["status"] == "RECEIVED"

    def test_store_atlas_references(self, bloom_content):
        """Atlas reference EUIDs can be stored in json_addl."""
        from sqlalchemy.orm.attributes import flag_modified

        templates = bloom_content.query_template_by_component_v2(
            "content", "specimen", "buccal-swab", "1.0"
        )
        result = bloom_content.create_empty_content(templates[0].euid)
        instance = result[0][0]

        instance.json_addl["properties"]["atlas_patient_euid"] = "PT42"
        instance.json_addl["properties"]["atlas_order_euid"] = "OR7"
        flag_modified(instance, "json_addl")
        bloom_content.session.commit()

        refreshed = bloom_content.get_by_euid(instance.euid)
        assert refreshed.json_addl["properties"]["atlas_patient_euid"] == "PT42"
        assert refreshed.json_addl["properties"]["atlas_order_euid"] == "OR7"
