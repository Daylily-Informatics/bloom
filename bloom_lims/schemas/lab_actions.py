"""Schemas for Bloom lab action APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PlatformName = Literal["ILMN", "ONT", "Ultima", "PacBio", "CompleteGenomics"]
RunSetStatus = Literal["created", "running", "abandoned", "complete", "error"]


class WellPosition(BaseModel):
    row: str
    col: int

    @field_validator("row", mode="before")
    @classmethod
    def normalize_row(cls, value):
        row = str(value or "").strip().upper()
        if row not in tuple("ABCDEFGH"):
            raise ValueError("row must be A-H")
        return row

    @field_validator("col", mode="before")
    @classmethod
    def normalize_col(cls, value):
        col = int(value)
        if col < 1 or col > 12:
            raise ValueError("col must be 1-12")
        return col

    @property
    def name(self) -> str:
        return f"{self.row}{self.col}"


class ExtractionTubeAssignment(BaseModel):
    tube_euid: str
    row: str | None = None
    col: int | None = None
    quant: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_position_pair(self) -> "ExtractionTubeAssignment":
        if (self.row is None) ^ (self.col is None):
            raise ValueError("row and col must be provided together")
        if self.row is not None and self.col is not None:
            WellPosition(row=self.row, col=self.col)
        return self


class RunSetInput(BaseModel):
    name: str | None = None
    description: str | None = None
    members: list[str] = Field(default_factory=list)
    external_members: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: RunSetStatus = "created"


class ExtractionPlateRequest(BaseModel):
    mode: Literal["auto", "directed"] = "auto"
    tube_euids: list[str] = Field(default_factory=list)
    assignments: list[ExtractionTubeAssignment] = Field(default_factory=list)
    plate_euid: str | None = None
    plate_name: str | None = None
    create_run_set: bool = False
    run_set: RunSetInput | None = None
    print_new_container_barcodes: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> "ExtractionPlateRequest":
        if self.mode == "auto":
            if self.assignments:
                raise ValueError("auto mode accepts tube_euids, not assignments")
            if not self.tube_euids:
                raise ValueError("tube_euids is required for auto mode")
        if self.mode == "directed":
            if self.tube_euids:
                raise ValueError("directed mode accepts assignments, not tube_euids")
            if not self.assignments:
                raise ValueError("assignments is required for directed mode")
        return self


class LibraryPlateAssignment(BaseModel):
    source_well_euid: str
    row: str | None = None
    col: int | None = None
    # index_barcode remains the compatibility field used by existing callers.
    # For dual-index Illumina libraries it must equal i7_sequence.
    index_barcode: str | None = None
    index_euid: str | None = None
    i7_sequence: str | None = None
    i5_sequence: str | None = None
    index_orientation: str | None = None
    index_set: str | None = None
    barcode_name: str | None = None
    index_platform: Literal["ILMN", "ONT"] | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_position_pair(self) -> "LibraryPlateAssignment":
        if (self.row is None) ^ (self.col is None):
            raise ValueError("row and col must be provided together")
        if self.row is not None and self.col is not None:
            WellPosition(row=self.row, col=self.col)
        if self.i5_sequence and not self.i7_sequence:
            raise ValueError("i7_sequence is required when i5_sequence is provided")
        if (
            self.i7_sequence
            and self.index_barcode
            and self.i7_sequence != self.index_barcode
        ):
            raise ValueError("index_barcode must equal i7_sequence")
        if self.barcode_name and (self.i7_sequence or self.i5_sequence):
            raise ValueError("ONT barcode_name cannot be combined with i7/i5 sequences")
        return self


class SeqLibraryPlateRequest(BaseModel):
    mode: Literal["plate_1_to_1", "directed"] = "plate_1_to_1"
    source_plate_euid: str | None = None
    assignments: list[LibraryPlateAssignment] = Field(default_factory=list)
    plate_name: str | None = None
    create_run_set: bool = False
    run_set: RunSetInput | None = None
    print_new_container_barcodes: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> "SeqLibraryPlateRequest":
        if self.mode == "plate_1_to_1" and not self.source_plate_euid:
            raise ValueError("source_plate_euid is required for plate_1_to_1 mode")
        if self.mode == "directed" and not self.assignments:
            raise ValueError("assignments is required for directed mode")
        return self


class ExtractionQcAssignment(BaseModel):
    source_well_euid: str | None = None
    row: str | None = None
    col: int | None = None
    qc_row: str | None = None
    qc_col: int | None = None
    result: str | None = None
    status: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_position(self) -> "ExtractionQcAssignment":
        if self.source_well_euid and (self.row is not None or self.col is not None):
            raise ValueError("provide source_well_euid or row/col, not both")
        if not self.source_well_euid and (self.row is None or self.col is None):
            raise ValueError("source_well_euid or row/col is required")
        if (self.row is None) ^ (self.col is None):
            raise ValueError("row and col must be provided together")
        if self.row is not None and self.col is not None:
            WellPosition(row=self.row, col=self.col)
        if (self.qc_row is None) ^ (self.qc_col is None):
            raise ValueError("qc_row and qc_col must be provided together")
        if self.qc_row is not None and self.qc_col is not None:
            WellPosition(row=self.qc_row, col=self.qc_col)
        return self


class ExtractionQcPlateRequest(BaseModel):
    source_plate_euid: str | None = None
    qc_plate_euid: str | None = None
    qc_plate_name: str | None = None
    assignments: list[ExtractionQcAssignment] = Field(default_factory=list)
    create_run_set: bool = False
    run_set: RunSetInput | None = None

    @model_validator(mode="after")
    def validate_input(self) -> "ExtractionQcPlateRequest":
        if not self.source_plate_euid and not self.assignments:
            raise ValueError("source_plate_euid or assignments is required")
        return self


class PlateWellDataRecord(BaseModel):
    well_euid: str | None = None
    plate_euid: str | None = None
    row: str | None = None
    col: int | None = None
    name: str | None = None
    target: Literal["well", "content"] = "content"
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> "PlateWellDataRecord":
        if self.well_euid and (
            self.plate_euid or self.row is not None or self.col is not None
        ):
            raise ValueError("provide well_euid or plate_euid with row/col, not both")
        if not self.well_euid:
            if not self.plate_euid or self.row is None or self.col is None:
                raise ValueError("well_euid or plate_euid with row/col is required")
            WellPosition(row=self.row, col=self.col)
        return self


class PlateWellDataRequest(BaseModel):
    data_template_code: str = "data/operation/extraction-qc/1.0/"
    relationship_type: str = "well_associated_data"
    records: list[PlateWellDataRecord]
    create_run_set: bool = False
    run_set: RunSetInput | None = None

    @field_validator("records")
    @classmethod
    def validate_records(cls, value):
        if not value:
            raise ValueError("records must not be empty")
        return value


class SeqLibraryPoolRequest(BaseModel):
    input_euids: list[str]
    platform: PlatformName = "ILMN"
    pool_tube_euid: str | None = None
    pool_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    create_run_set: bool = False
    run_set: RunSetInput | None = None
    print_new_container_barcodes: bool = False

    @field_validator("input_euids")
    @classmethod
    def validate_inputs(cls, value):
        if not value:
            raise ValueError("input_euids must not be empty")
        return value


class SeqRunSetRequest(BaseModel):
    pool_tube_euid: str
    pool_content_euid: str | None = None
    platform: PlatformName = "ILMN"
    operator: str | None = None
    instrument_euid: str | None = None
    machine: str | None = None
    flowcell_barcode: str
    reagent_euids: list[str] = Field(default_factory=list)
    status: RunSetStatus = "created"
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LabSetRequest(BaseModel):
    name: str
    description: str | None = None
    members: list[str] = Field(default_factory=list)
    external_members: list[str] = Field(default_factory=list)
    operator: str | None = None
    instrument: str | None = None
    reagents: list[str] = Field(default_factory=list)
    machine: str | None = None
    flowcell_barcode: str | None = None
    status: RunSetStatus = "created"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LabSetMembersRequest(BaseModel):
    members: list[str] = Field(default_factory=list)
    external_members: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_members(self) -> "LabSetMembersRequest":
        if not self.members and not self.external_members:
            raise ValueError("members or external_members is required")
        return self


class PrintEuidRequest(BaseModel):
    euids: list[str]
    lab: str
    printer_id: str
    label_zpl_style: str
    copies: int = Field(default=1, ge=1, le=20)
    dry_run: bool = False

    @field_validator("euids")
    @classmethod
    def validate_euids(cls, value):
        if not value:
            raise ValueError("euids must not be empty")
        if len(value) > 500:
            raise ValueError("euids cannot exceed 500")
        return value
