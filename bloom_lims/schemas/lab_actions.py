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
    index_barcode: str | None = None
    index_euid: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_position_pair(self) -> "LibraryPlateAssignment":
        if (self.row is None) ^ (self.col is None):
            raise ValueError("row and col must be provided together")
        if self.row is not None and self.col is not None:
            WellPosition(row=self.row, col=self.col)
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


class PrintEuidRequest(BaseModel):
    euids: list[str]
    lab: str
    printer_id: str
    label_zpl_style: str
    copies: int = Field(default=1, ge=1, le=20)

    @field_validator("euids")
    @classmethod
    def validate_euids(cls, value):
        if not value:
            raise ValueError("euids must not be empty")
        if len(value) > 500:
            raise ValueError("euids cannot exceed 500")
        return value
