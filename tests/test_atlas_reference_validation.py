from __future__ import annotations

import pytest
from daylily_tapdb.euid import format_euid
from pydantic import ValidationError

from bloom_lims.schemas.beta_lab import AtlasFulfillmentContext
from bloom_lims.schemas.external_specimens import (
    AtlasReferences,
    ExternalSpecimenCreateRequest,
)


@pytest.fixture(autouse=True)
def _meridian_runtime(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ENVIRONMENT", "production")
    monkeypatch.setenv("MERIDIAN_DOMAIN_CODE", "Z")
    monkeypatch.setenv("MERIDIAN_SANDBOX_PREFIX", "")


def test_valid_atlas_testkit_euid_passes():
    testkit_euid = format_euid("AGX", 1, domain_code="Z")

    context = AtlasFulfillmentContext(
        atlas_tenant_id="tenant-1",
        atlas_testkit_euid=testkit_euid,
    )

    assert context.atlas_testkit_euid == testkit_euid


def test_ifm_kit_value_in_atlas_euid_field_fails():
    with pytest.raises(ValidationError, match="atlas_testkit_euid must be a Meridian EUID"):
        AtlasFulfillmentContext(
            atlas_tenant_id="tenant-1",
            atlas_testkit_euid="IFM-KIT-A6CB3433-01-01",
        )


def test_ifm_kit_value_in_kit_barcode_is_allowed():
    request = ExternalSpecimenCreateRequest(
        atlas_refs=AtlasReferences(kit_barcode="IFM-KIT-A6CB3433-01-01")
    )

    assert request.atlas_refs.kit_barcode == "IFM-KIT-A6CB3433-01-01"
