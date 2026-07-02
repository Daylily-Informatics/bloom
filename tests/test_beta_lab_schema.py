"""Schema regressions for Bloom beta lab payload contracts."""

from __future__ import annotations

import pytest

from bloom_lims.schemas.beta_lab import AtlasFulfillmentContext


def test_atlas_fulfillment_context_preserves_order_refs():
    context = AtlasFulfillmentContext(
        atlas_tenant_id="tenant-1",
        atlas_order_euid="Z-AGX-ORDER1",
        atlas_order_test_euid="Z-AGX-TEST1",
        atlas_order_test_euids=["Z-AGX-TEST1", "Z-AGX-TEST2"],
        fulfillment_slots=[
            {
                "atlas_order_test_euid": "Z-AGX-TEST2",
                "atlas_fulfillment_slot_euid": "Z-AGX-SLOT1",
            }
        ],
    )

    payload = context.model_dump()

    assert payload["atlas_order_euid"] == "Z-AGX-ORDER1"
    assert payload["atlas_order_test_euid"] == "Z-AGX-TEST1"
    assert payload["atlas_order_test_euids"] == [
        "Z-AGX-TEST1",
        "Z-AGX-TEST2",
    ]
    assert (
        payload["fulfillment_slots"][0]["atlas_fulfillment_slot_euid"] == "Z-AGX-SLOT1"
    )


def test_atlas_fulfillment_context_requires_order_for_order_tests():
    with pytest.raises(ValueError, match="atlas_order_euid is required"):
        AtlasFulfillmentContext(
            atlas_tenant_id="tenant-1",
            atlas_order_test_euid="Z-AGX-TEST1",
        )
