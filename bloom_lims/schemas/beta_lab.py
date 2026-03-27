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


class AtlasFulfillmentItemReference(BaseModel):
    atlas_test_euid: str
    atlas_test_fulfillment_item_euid: str


class AtlasCollectionEventSnapshot(BaseModel):
    collection_event_euid: str
    collected_at: str | None = None
    site_euid: str | None = None
    collection_type: str | None = None
    collected_by: str | None = None
    expected_mrn: str | None = None
    expected_dob: str | None = None
    expected_name: str | None = None
    expected_label_text: str | None = None


class AtlasFulfillmentContext(BaseModel):
    atlas_tenant_id: str
    atlas_trf_euid: str | None = None
    atlas_test_euid: str | None = None
    atlas_test_euids: list[str] = Field(default_factory=list)
    atlas_patient_euid: str | None = None
    atlas_testkit_euid: str | None = None
    atlas_shipment_euid: str | None = None
    atlas_organization_site_euid: str | None = None
    atlas_collection_event_euid: str | None = None
    collection_event_snapshot: AtlasCollectionEventSnapshot | None = None
    fulfillment_items: list[AtlasFulfillmentItemReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_context(self) -> "AtlasFulfillmentContext":
        if not self.atlas_tenant_id.strip():
            raise ValueError("atlas_tenant_id is required")
        if self.atlas_trf_euid is not None and not self.atlas_trf_euid.strip():
            raise ValueError("atlas_trf_euid must not be empty when provided")
        if self.atlas_test_euid is not None and not self.atlas_test_euid.strip():
            raise ValueError("atlas_test_euid must not be empty when provided")
        normalized_test_euids: list[str] = []
        seen_test_euids: set[str] = set()
        primary_test_euid = str(self.atlas_test_euid or "").strip()
        if primary_test_euid:
            seen_test_euids.add(primary_test_euid)
            normalized_test_euids.append(primary_test_euid)
        for item in self.atlas_test_euids:
            clean_item = str(item or "").strip()
            if not clean_item or clean_item in seen_test_euids:
                continue
            seen_test_euids.add(clean_item)
            normalized_test_euids.append(clean_item)
        self.atlas_test_euids = normalized_test_euids
        if self.atlas_test_euid is None and self.atlas_test_euids:
            self.atlas_test_euid = self.atlas_test_euids[0]
        if self.atlas_patient_euid is not None and not self.atlas_patient_euid.strip():
            raise ValueError("atlas_patient_euid must not be empty when provided")
        if self.atlas_testkit_euid is not None and not self.atlas_testkit_euid.strip():
            raise ValueError("atlas_testkit_euid must not be empty when provided")
        if self.atlas_shipment_euid is not None and not self.atlas_shipment_euid.strip():
            raise ValueError("atlas_shipment_euid must not be empty when provided")
        if (
            self.atlas_organization_site_euid is not None
            and not self.atlas_organization_site_euid.strip()
        ):
            raise ValueError("atlas_organization_site_euid must not be empty when provided")
        if (
            self.atlas_collection_event_euid is not None
            and not self.atlas_collection_event_euid.strip()
        ):
            raise ValueError("atlas_collection_event_euid must not be empty when provided")
        if self.collection_event_snapshot is not None:
            if not self.collection_event_snapshot.collection_event_euid.strip():
                raise ValueError("collection_event_snapshot.collection_event_euid is required")
            if (
                self.atlas_collection_event_euid is not None
                and self.collection_event_snapshot.collection_event_euid.strip()
                != self.atlas_collection_event_euid.strip()
            ):
                raise ValueError(
                    "collection_event_snapshot.collection_event_euid must match "
                    "atlas_collection_event_euid"
                )
        if self.fulfillment_items:
            if not (self.atlas_trf_euid and self.atlas_trf_euid.strip()):
                raise ValueError("atlas_trf_euid is required when fulfillment_items are provided")
        elif (self.atlas_test_euid is not None or self.atlas_test_euids) and not self.atlas_trf_euid:
            raise ValueError("atlas_trf_euid is required when atlas_test_euid is provided")
        return self


class BetaAcceptedMaterialCreateRequest(BaseModel):
    specimen_template_code: str = Field(default="content/specimen/blood-whole/1.0")
    specimen_name: str | None = None
    container_euid: str | None = None
    container_template_code: str = Field(default="container/tube/tube-generic-10ml/1.0")
    status: str = Field(default="active")
    properties: dict[str, Any] = Field(default_factory=dict)
    atlas_context: AtlasFulfillmentContext


class BetaTubeCreateRequest(BaseModel):
    container_template_code: str = Field(default="container/tube/tube-generic-10ml/1.0")
    status: str = Field(default="active")
    properties: dict[str, Any] = Field(default_factory=dict)
    atlas_context: AtlasFulfillmentContext


class BetaTubeUpdateRequest(BaseModel):
    status: str | None = None
    properties: dict[str, Any] | None = None
    atlas_context: AtlasFulfillmentContext | None = None


class BetaSpecimenUpdateRequest(BaseModel):
    status: str | None = None
    properties: dict[str, Any] | None = None
    atlas_context: AtlasFulfillmentContext | None = None


class BetaMaterialResponse(BaseModel):
    specimen_euid: str
    container_euid: str | None
    status: str
    atlas_context: dict[str, Any]
    properties: dict[str, Any]
    idempotency_key: str | None = None
    current_queue: str | None = None
    created: bool = True


class BetaTubeResponse(BaseModel):
    container_euid: str
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
    atlas_test_fulfillment_item_euid: str | None = None
    claim_euid: str | None = None
    consume_source: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaExtractionResponse(BaseModel):
    source_specimen_euid: str
    plate_euid: str
    well_euid: str
    well_name: str
    extraction_output_euid: str
    atlas_test_fulfillment_item_euid: str
    current_queue: str
    idempotent_replay: bool = False


class BetaPostExtractQCRequest(BaseModel):
    extraction_output_euid: str
    passed: bool
    next_queue: Literal["ilmn_lib_prep", "ont_lib_prep"] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    claim_euid: str | None = None
    consume_source: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaLibraryPrepResponse(BaseModel):
    source_extraction_output_euid: str
    library_prep_output_euid: str
    library_material_euid: str | None = None
    library_container_euid: str | None = None
    library_plate_euid: str | None = None
    library_well_euid: str | None = None
    atlas_test_fulfillment_item_euid: str
    current_queue: str
    idempotent_replay: bool = False


class BetaPoolCreateRequest(BaseModel):
    member_euids: list[str]
    platform: Literal["ILMN", "ONT"]
    pool_name: str | None = None
    claim_euid: str | None = None
    consume_members: bool = False
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
    claim_euid: str | None = None
    consume_pool: bool = False
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
    atlas_test_fulfillment_item_euid: str


class BetaClaimCreateRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaClaimReleaseRequest(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaClaimResponse(BaseModel):
    claim_euid: str
    material_euid: str
    queue_name: CanonicalQueueName
    work_item_euid: str
    status: str
    metadata: dict[str, Any]
    idempotent_replay: bool = False


class BetaReservationCreateRequest(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaReservationReleaseRequest(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaReservationResponse(BaseModel):
    reservation_euid: str
    material_euid: str
    status: str
    metadata: dict[str, Any]
    idempotent_replay: bool = False


class BetaConsumeMaterialRequest(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BetaConsumeMaterialResponse(BaseModel):
    consumption_event_euid: str
    material_euid: str
    consumed: bool = True
    metadata: dict[str, Any]
    idempotent_replay: bool = False
