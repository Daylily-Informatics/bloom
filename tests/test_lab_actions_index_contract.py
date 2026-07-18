from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from bloom_lims.domain.lab_actions import LabActionsService
from bloom_lims.schemas.lab_actions import LibraryPlateAssignment


def test_dual_index_assignment_requires_consistent_i7_compatibility_value() -> None:
    assignment = LibraryPlateAssignment(
        source_well_euid="source-well",
        row="A",
        col=1,
        index_barcode="ACGTACGT",
        i7_sequence="ACGTACGT",
        i5_sequence="TGCATGCA",
        index_euid="persisted-index-object",
        index_platform="ILMN",
    )

    assert assignment.i7_sequence == assignment.index_barcode
    assert assignment.i5_sequence == "TGCATGCA"

    with pytest.raises(ValidationError, match="index_barcode must equal i7_sequence"):
        LibraryPlateAssignment(
            source_well_euid="source-well",
            index_barcode="AAAAAAAA",
            i7_sequence="CCCCCCCC",
            i5_sequence="GGGGGGGG",
        )


def test_ont_barcode_name_does_not_invent_a_sequence() -> None:
    assignment = LibraryPlateAssignment(
        source_well_euid="source-well",
        barcode_name="barcode01",
        index_set="SQK-NBD114-24",
        index_platform="ONT",
        index_euid="persisted-index-object",
    )

    assert assignment.barcode_name == "barcode01"
    assert assignment.i7_sequence is None
    assert assignment.i5_sequence is None

    with pytest.raises(ValidationError, match="cannot be combined"):
        LibraryPlateAssignment(
            source_well_euid="source-well",
            barcode_name="barcode01",
            i7_sequence="ACGTACGT",
        )


def test_illumina_sample_sheet_emits_index_and_index2() -> None:
    service = object.__new__(LabActionsService)
    content = service._illumina_sample_sheet(
        run_set=SimpleNamespace(euid="run-set-receipt"),
        props={"flowcell_barcode": "FLOWCELL", "operator": "operator"},
        data_rows=[
            {
                "Sample_ID": "library-receipt",
                "Sample_Name": "sample",
                "index": "ACGTACGT",
                "index2": "TGCATGCA",
                "barcode_name": "",
                "Description": "{}",
            }
        ],
    )

    assert "Sample_ID,Sample_Name,index,index2,Description" in content
    assert "library-receipt,sample,ACGTACGT,TGCATGCA,{}" in content


def test_ont_sample_sheet_prefers_explicit_barcode_name() -> None:
    service = object.__new__(LabActionsService)
    content = service._ont_sample_sheet(
        run_set=SimpleNamespace(euid="run-set-receipt"),
        props={"flowcell_barcode": "FLOWCELL", "operator": "operator"},
        data_rows=[
            {
                "Sample_ID": "library-receipt",
                "Sample_Name": "sample",
                "index": "",
                "index2": "",
                "barcode_name": "barcode01",
                "Description": "{}",
            }
        ],
    )

    assert "library-receipt\tsample\tbarcode01" in content
