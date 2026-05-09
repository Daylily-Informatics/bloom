"""Validation helpers for Atlas reference fields persisted in Bloom."""

from __future__ import annotations

from typing import Any

from bloom_lims.schemas.base import validate_euid

_ATLAS_EUID_REFERENCE_TYPES = frozenset(
    {
        "atlas_trf",
        "atlas_test",
        "atlas_patient",
        "atlas_testkit",
        "atlas_shipment",
        "atlas_organization_site",
        "atlas_collection_event",
        "atlas_test_fulfillment_item",
        "atlas_test_process_item",
    }
)


def validate_meridian_euid_field(field_name: str, value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} must not be empty when provided")
    try:
        return validate_euid(clean)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a Meridian EUID") from exc


def validate_optional_meridian_euid_field(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{field_name} must not be empty when provided")
    return validate_meridian_euid_field(field_name, clean)


def is_atlas_euid_field(field_name: str) -> bool:
    clean = str(field_name or "").strip()
    return clean.startswith("atlas_") and clean.endswith("_euid")


def reference_type_declares_atlas_euid(reference_type: str) -> bool:
    clean = str(reference_type or "").strip()
    return is_atlas_euid_field(clean) or clean in _ATLAS_EUID_REFERENCE_TYPES


def validate_atlas_euid_properties(properties: dict[str, Any]) -> dict[str, Any]:
    for field_name, value in list(properties.items()):
        if is_atlas_euid_field(field_name) and str(value or "").strip():
            properties[field_name] = validate_meridian_euid_field(field_name, value)

    reference_type = str(properties.get("reference_type") or "").strip()
    if reference_type_declares_atlas_euid(reference_type):
        reference_value = validate_meridian_euid_field(
            f"{reference_type}.reference_value",
            properties.get("reference_value"),
        )
        properties["reference_value"] = reference_value
        properties["foreign_reference"] = reference_value
    return properties
