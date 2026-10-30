"""Bounded, exact owner-integration request and integrity contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from bloom_lims.schemas.base import validate_euid


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def exact_euid(value: str) -> str:
    if validate_euid(value) != value:
        raise ValueError("An exact canonical owning-service EUID is required")
    return value


class LineageSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_euid: StrictStr = Field(min_length=1, max_length=128)
    child_euid: StrictStr = Field(min_length=1, max_length=128)
    relationship_type: StrictStr = Field(min_length=1, max_length=128)

    @field_validator("parent_euid", "child_euid")
    @classmethod
    def validate_exact_euid(cls, value: str) -> str:
        return exact_euid(value)

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("An exact relationship type is required")
        return value

    def identity(self) -> tuple[str, str, str]:
        return self.parent_euid, self.child_euid, self.relationship_type


class OwnerSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_euids: list[StrictStr] = Field(min_length=1, max_length=128)
    lineage_selectors: list[LineageSelector] = Field(max_length=128)

    @model_validator(mode="after")
    def validate_complete_request(self) -> "OwnerSnapshotRequest":
        objects = set(self.object_euids)
        if len(objects) != len(self.object_euids):
            raise ValueError("Duplicate object EUIDs are not allowed")
        for euid in self.object_euids:
            if len(euid) > 128:
                raise ValueError("Object EUID exceeds the request bound")
            exact_euid(euid)
        selectors = [item.identity() for item in self.lineage_selectors]
        if len(set(selectors)) != len(selectors):
            raise ValueError("Duplicate lineage selectors are not allowed")
        if any(parent not in objects or child not in objects for parent, child, _ in selectors):
            raise ValueError("Every lineage endpoint must be explicitly requested")
        return self

    def canonical_request(self) -> dict[str, Any]:
        return {
            "object_euids": sorted(self.object_euids),
            "lineage_selectors": [
                item.model_dump()
                for item in sorted(self.lineage_selectors, key=lambda item: item.identity())
            ],
        }


class PropertyNamespaceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_json_addl_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    value: dict[str, Any]

    @field_validator("value")
    @classmethod
    def validate_bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(canonical_json_bytes(value)) > 65536:
            raise ValueError("Property namespace exceeds the 64 KiB bound")
        return value
