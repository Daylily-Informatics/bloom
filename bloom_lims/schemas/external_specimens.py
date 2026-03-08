"""Schemas for Atlas-facing external specimen APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class AtlasReferences(BaseModel):
    order_number: str | None = None
    patient_id: str | None = None
    shipment_number: str | None = None
    kit_barcode: str | None = None
    atlas_tenant_id: str | None = None
    atlas_order_euid: str | None = None
    atlas_test_order_euid: str | None = None


class ExternalSpecimenCreateRequest(BaseModel):
    specimen_template_code: str = Field(default="content/specimen/generic/1.0")
    specimen_name: str | None = None
    container_euid: str | None = None
    container_template_code: str = Field(default="container/tube/generic/1.0")
    status: str = Field(default="active")
    properties: dict[str, Any] = Field(default_factory=dict)
    atlas_refs: AtlasReferences

    @model_validator(mode="after")
    def validate_references(self) -> "ExternalSpecimenCreateRequest":
        refs = self.atlas_refs
        if not any(
            [
                refs.order_number,
                refs.patient_id,
                refs.shipment_number,
                refs.kit_barcode,
                refs.atlas_tenant_id,
                refs.atlas_order_euid,
                refs.atlas_test_order_euid,
            ]
        ):
            raise ValueError("At least one Atlas reference is required")
        return self


class ExternalSpecimenUpdateRequest(BaseModel):
    specimen_name: str | None = None
    status: str | None = None
    container_euid: str | None = None
    properties: dict[str, Any] | None = None
    atlas_refs: AtlasReferences | None = None


class ExternalSpecimenResponse(BaseModel):
    specimen_euid: str
    container_euid: str | None
    status: str
    atlas_refs: dict[str, Any]
    properties: dict[str, Any]
    idempotency_key: str | None = None
    created: bool = True


class ExternalSpecimenLookupResponse(BaseModel):
    items: list[ExternalSpecimenResponse]
    total: int
