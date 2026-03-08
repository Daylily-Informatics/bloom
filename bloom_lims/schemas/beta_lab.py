"""Schemas for Bloom beta queue/material/run APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

CanonicalQueueName = Literal[
    "extraction_prod",
    "extraction_rnd",
    "post_extract_qc",
    "ilmn_lib_prep",
    "ont_lib_prep",
    "ilmn_seq_pool",
    "ont_seq_pool",
    "ilmn_start_seq_run",
    "ont_start_seq_run",
]


class AtlasProcessItemReference(BaseModel):
    atlas_test_euid: str
    atlas_test_process_item_euid: str


class AtlasProcessContext(BaseModel):
    atlas_tenant_id: str
    atlas_trf_euid: str
    process_items: list[AtlasProcessItemReference]

    @model_validator(mode="after")
    def validate_context(self) -> "AtlasProcessContext":
        if not self.atlas_tenant_id.strip():
            raise ValueError("atlas_tenant_id is required")
        if not self.atlas_trf_euid.strip():
            raise ValueError("atlas_trf_euid is required")
        if not self.process_items:
            raise ValueError("process_items must not be empty")
        return self


class BetaAcceptedMaterialCreateRequest(BaseModel):
    specimen_template_code: str = Field(default="content/specimen/blood-whole/1.0")
    specimen_name: str | None = None
    container_euid: str | None = None
    container_template_code: str = Field(default="container/tube/tube-generic-10ml/1.0")
    status: str = Field(default="active")
    properties: dict[str, Any] = Field(default_factory=dict)
    atlas_context: AtlasProcessContext


class BetaMaterialResponse(BaseModel):
    specimen_euid: str
    container_euid: str | None
    status: str
    atlas_context: dict[str, Any]
    properties: dict[str, Any]
    idempotency_key: str | None = None
    current_queue: str | None = None
    created: bool = True


class BetaQueueTransitionRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaQueueTransitionResponse(BaseModel):
    material_euid: str
    queue_euid: str
    queue_name: CanonicalQueueName
    previous_queue: str | None = None
    current_queue: str
    idempotent_replay: bool = False


class BetaExtractionCreateRequest(BaseModel):
    source_specimen_euid: str
    plate_euid: str | None = None
    plate_template_code: str = Field(default="container/plate/fixed-plate-24/1.0")
    plate_name: str | None = None
    well_name: str
    extraction_type: Literal["cfdna", "gdna"] = Field(default="cfdna")
    output_name: str | None = None
    atlas_test_process_item_euid: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaExtractionResponse(BaseModel):
    source_specimen_euid: str
    plate_euid: str
    well_euid: str
    well_name: str
    extraction_output_euid: str
    atlas_test_process_item_euid: str
    current_queue: str
    idempotent_replay: bool = False


class BetaPostExtractQCRequest(BaseModel):
    extraction_output_euid: str
    passed: bool
    next_queue: Literal["ilmn_lib_prep", "ont_lib_prep"] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_next_queue(self) -> "BetaPostExtractQCRequest":
        if self.passed and not self.next_queue:
            raise ValueError("next_queue is required when passed=true")
        return self


class BetaPostExtractQCResponse(BaseModel):
    extraction_output_euid: str
    qc_passed: bool
    current_queue: str | None
    idempotent_replay: bool = False


class BetaLibraryPrepCreateRequest(BaseModel):
    source_extraction_output_euid: str
    platform: Literal["ILMN", "ONT"]
    output_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaLibraryPrepResponse(BaseModel):
    source_extraction_output_euid: str
    library_prep_output_euid: str
    atlas_test_process_item_euid: str
    current_queue: str
    idempotent_replay: bool = False


class BetaPoolCreateRequest(BaseModel):
    member_euids: list[str]
    platform: Literal["ILMN", "ONT"]
    pool_name: str | None = None
    pool_container_template_code: str = Field(
        default="container/tube/tube-generic-10ml/1.0"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_members(self) -> "BetaPoolCreateRequest":
        if not self.member_euids:
            raise ValueError("member_euids must not be empty")
        return self


class BetaPoolResponse(BaseModel):
    pool_euid: str
    pool_container_euid: str
    current_queue: str
    member_euids: list[str]
    idempotent_replay: bool = False


class BetaRunAssignmentInput(BaseModel):
    lane: str
    library_barcode: str
    library_prep_output_euid: str


class BetaRunArtifactInput(BaseModel):
    artifact_type: str
    bucket: str
    filename: str
    lane: str | None = None
    library_barcode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaRunCreateRequest(BaseModel):
    pool_euid: str
    platform: Literal["ILMN", "ONT"]
    flowcell_id: str
    run_name: str | None = None
    status: Literal["started", "completed"] = Field(default="completed")
    metadata: dict[str, Any] = Field(default_factory=dict)
    assignments: list[BetaRunAssignmentInput]
    artifacts: list[BetaRunArtifactInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_assignments(self) -> "BetaRunCreateRequest":
        if not self.flowcell_id.strip():
            raise ValueError("flowcell_id must not be empty")
        if not self.assignments:
            raise ValueError("assignments must not be empty")
        return self


class BetaRunResponse(BaseModel):
    run_euid: str
    pool_euid: str
    flowcell_id: str
    run_folder: str
    status: str
    artifact_count: int
    assignment_count: int
    idempotent_replay: bool = False


class BetaRunResolutionResponse(BaseModel):
    run_euid: str
    flowcell_id: str
    lane: str
    library_barcode: str
    sequenced_library_assignment_euid: str
    atlas_tenant_id: str
    atlas_trf_euid: str
    atlas_test_euid: str
    atlas_test_process_item_euid: str
