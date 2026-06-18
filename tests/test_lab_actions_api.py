"""API coverage for Bloom lab actions."""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from unittest.mock import patch

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
os.environ["BLOOM_OAUTH"] = "no"

from fastapi.testclient import TestClient

from bloom_lims.domain.lab_action_spreadsheets import parse_workbook
from main import app


def _client() -> TestClient:
    return TestClient(app)


def _create_object(
    client: TestClient,
    *,
    category: str,
    type_name: str,
    subtype: str,
    name: str,
    version: str = "1.0",
    properties: dict | None = None,
    count: int = 1,
) -> dict:
    response = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": category,
            "type": type_name,
            "subtype": subtype,
            "version": version,
            "name": name,
            "properties": properties or {},
            "count": count,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _link_material(client: TestClient, *, container_euid: str, content_euid: str) -> None:
    response = client.post(
        "/api/v1/lineages/",
        json={
            "parent_euid": container_euid,
            "child_euid": content_euid,
            "relationship_type": "HOLDS_MATERIAL",
        },
    )
    assert response.status_code == 200, response.text


def _create_filled_tube(client: TestClient, *, suffix: str) -> tuple[str, str]:
    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        tube = _create_object(
            client,
            category="container",
            type_name="tube",
            subtype="tube-generic-10ml",
            name=f"pytest incoming tube {suffix}",
        )
    content = _create_object(
        client,
        category="content",
        type_name="specimen",
        subtype="buccal-swab",
        name=f"pytest buccal specimen {suffix}",
    )
    _link_material(client, container_euid=tube["euid"], content_euid=content["euid"])
    return tube["euid"], content["euid"]


def _create_plate(client: TestClient, *, name: str) -> str:
    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        plate = _create_object(
            client,
            category="container",
            type_name="plate",
            subtype="fixed-plate-96",
            name=name,
        )
    return plate["euid"]


def _create_reagent_index(client: TestClient, *, name: str) -> str:
    reagent = _create_object(
        client,
        category="content",
        type_name="reagent",
        subtype="sequencing-index",
        name=name,
    )
    return reagent["euid"]


def _create_instrument(client: TestClient, *, name: str) -> str:
    instrument = _create_object(
        client,
        category="equipment",
        type_name="sequencers",
        subtype="novaseq-6000",
        name=name,
    )
    return instrument["euid"]


def test_lab_actions_full_ilmn_flow_and_csv_export() -> None:
    client = _client()
    tube_1, _ = _create_filled_tube(client, suffix="a")
    tube_2, _ = _create_filled_tube(client, suffix="b")

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        extraction = client.post(
            "/api/v1/lab-actions/extraction-plates",
            json={
                "mode": "auto",
                "tube_euids": [tube_1, tube_2],
                "plate_name": "pytest extraction plate",
                "create_run_set": True,
            },
        )
    assert extraction.status_code == 200, extraction.text
    extraction_payload = extraction.json()
    assert extraction_payload["plate_euid"]
    assert extraction_payload["run_set_euid"]
    assert [item["well_name"] for item in extraction_payload["mappings"]] == [
        "A1",
        "A2",
    ]
    assert all(item["output_content_euid"] for item in extraction_payload["mappings"])

    plate_csv = client.get(
        f"/api/v1/lab-actions/plates/{extraction_payload['plate_euid']}/mapping.csv"
    )
    assert plate_csv.status_code == 200, plate_csv.text
    assert "tube_euid,plate_euid,well_euid,well_row,well_col" in plate_csv.text
    assert tube_1 in plate_csv.text

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        library = client.post(
            "/api/v1/lab-actions/seq-library-plates",
            json={
                "mode": "plate_1_to_1",
                "source_plate_euid": extraction_payload["plate_euid"],
                "plate_name": "pytest library plate",
            },
        )
    assert library.status_code == 200, library.text
    library_payload = library.json()
    assert library_payload["plate_euid"]
    assert len(library_payload["mappings"]) == 2
    library_contents = [
        item["library_content_euid"] for item in library_payload["mappings"]
    ]

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        pool = client.post(
            "/api/v1/lab-actions/seq-library-pools",
            json={
                "input_euids": library_contents,
                "platform": "ILMN",
                "pool_name": "pytest sequencing pool",
            },
        )
    assert pool.status_code == 200, pool.text
    pool_payload = pool.json()
    assert pool_payload["pool_tube_euid"]
    assert pool_payload["pool_content_euid"]
    assert pool_payload["member_euids"] == library_contents

    seq_run = client.post(
        "/api/v1/lab-actions/seq-runs",
        json={
            "pool_tube_euid": pool_payload["pool_tube_euid"],
            "pool_content_euid": pool_payload["pool_content_euid"],
            "platform": "ILMN",
            "operator": "pytest@example.com",
            "flowcell_barcode": "PYTEST-FLOWCELL",
            "status": "created",
        },
    )
    assert seq_run.status_code == 200, seq_run.text
    run_payload = seq_run.json()
    assert run_payload["set_euid"]
    assert run_payload["assignments"]
    assert run_payload["assignments"][0]["flowcell_id"] == "PYTEST-FLOWCELL"
    assert run_payload["assignments"][0]["lane"] == "1"

    sample_sheet = client.get(
        f"/api/v1/lab-actions/seq-runs/{run_payload['set_euid']}/samplesheet"
    )
    assert sample_sheet.status_code == 200, sample_sheet.text
    assert "[Header]" in sample_sheet.text
    assert f"RunSetEUID,{run_payload['set_euid']}" in sample_sheet.text
    assert "PYTEST-FLOWCELL" in sample_sheet.text
    for library_content in library_contents:
        assert library_content in sample_sheet.text


def test_lab_actions_validation_and_ont_samplesheet_download() -> None:
    client = _client()
    invalid = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={"mode": "auto", "tube_euids": []},
    )
    assert invalid.status_code == 422

    tube, _ = _create_filled_tube(client, suffix="non-ilmn")
    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        pool = client.post(
            "/api/v1/lab-actions/seq-library-pools",
            json={
                "input_euids": [tube],
                "platform": "ONT",
                "pool_name": "pytest ont pool",
            },
        )
    assert pool.status_code == 200, pool.text
    run = client.post(
        "/api/v1/lab-actions/seq-runs",
        json={
            "pool_tube_euid": pool.json()["pool_tube_euid"],
            "pool_content_euid": pool.json()["pool_content_euid"],
            "platform": "ONT",
            "flowcell_barcode": "ONT-FLOWCELL",
        },
    )
    assert run.status_code == 200, run.text
    sample_sheet = client.get(
        f"/api/v1/lab-actions/seq-runs/{run.json()['set_euid']}/samplesheet"
    )
    assert sample_sheet.status_code == 200, sample_sheet.text
    assert sample_sheet.headers["content-type"].startswith("text/tab-separated-values")
    assert "_ONT_manifest.tsv" in sample_sheet.headers["content-disposition"]
    assert "sample_id\talias\tbarcode\trun_set_euid" in sample_sheet.text
    assert run.json()["set_euid"] in sample_sheet.text
    assert "ONT-FLOWCELL" in sample_sheet.text


def test_object_creation_count_and_print_euid_mock() -> None:
    client = _client()
    created = _create_object(
        client,
        category="set",
        type_name="run-set",
        subtype="generic",
        version="1.01",
        name="pytest run set",
        count=3,
    )
    assert len(created["created_euids"]) == 3
    assert created["euid"] == created["created_euids"][0]

    with patch("bloom_lims.domain.lab_actions.ZebraDayService") as service_cls:
        service = service_cls.return_value
        service.submit_print_job.side_effect = [
            {"job_euid": f"JOB-{index}", "status": "queued"} for index in range(3)
        ]
        response = client.post(
            "/api/v1/lab-actions/print-euids",
            json={
                "euids": created["created_euids"],
                "lab": "SSF",
                "printer_id": "pytest-printer",
                "label_zpl_style": "euid",
                "copies": 1,
                "dry_run": True,
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["printed"] == 0
    assert response.json()["dry_run"] is True
    assert service.submit_print_job.call_count == 0
    assert len(response.json()["results"]) == 3

    recursive_batch = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "plate",
            "subtype": "fixed-plate-96",
            "version": "1.0",
            "name": "unsafe recursive plate batch",
            "count": 2,
        },
    )
    assert recursive_batch.status_code == 400
    assert "recursive templates" in recursive_batch.json()["detail"]


def test_lab_actions_gui_renders_wizard() -> None:
    client = _client()
    response = client.get("/lab-actions")
    assert response.status_code == 200, response.text
    html = response.text
    assert "Lab Actions" in html
    assert "Extraction Plate" in html
    assert "Sequencing-Library Plate" in html
    assert "Sequencing Pool Tube" in html
    assert "Sequencing Run Set" in html
    assert "/api/v1/lab-actions/extraction-plates" in html
    assert 'data-testid="bloom-lab-library-assignments"' in html
    assert 'data-testid="bloom-lab-run-platform"' in html
    assert "mode: 'directed'" in html
    assert "Download ${platform} sample sheet" in html


def test_directed_extraction_into_existing_plate_with_quant_and_reuse_guard() -> None:
    client = _client()
    existing_plate_euid = _create_plate(client, name="pytest existing extraction plate")
    tube, _ = _create_filled_tube(client, suffix="directed")

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        response = client.post(
            "/api/v1/lab-actions/extraction-plates",
            json={
                "mode": "directed",
                "plate_euid": existing_plate_euid,
                "assignments": [
                    {
                        "tube_euid": tube,
                        "row": "B",
                        "col": 3,
                        "quant": {
                            "method": "Qubit",
                            "concentration": 42.5,
                            "concentration_units": "ng/uL",
                        },
                    }
                ],
                "run_set": {
                    "name": "pytest directed extraction set",
                    "members": [tube],
                    "external_members": ["atlas:pytest-external-member"],
                    "metadata": {"purpose": "directed-test"},
                },
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plate_euid"] == existing_plate_euid
    assert payload["new_container_euids"] == []
    assert payload["run_set_euid"]
    assert payload["mappings"][0]["well_name"] == "B3"
    assert payload["mappings"][0]["quant_euid"]

    repeat = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={
            "mode": "directed",
            "plate_euid": existing_plate_euid,
            "assignments": [{"tube_euid": tube, "row": "B", "col": 3}],
        },
    )
    assert repeat.status_code == 400
    assert "already filled" in repeat.json()["detail"]


def test_directed_extraction_rejects_duplicate_tubes_and_wells() -> None:
    client = _client()
    tube_1, _ = _create_filled_tube(client, suffix="dup-1")
    tube_2, _ = _create_filled_tube(client, suffix="dup-2")

    duplicate_tube = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={
            "mode": "directed",
            "assignments": [
                {"tube_euid": tube_1, "row": "A", "col": 1},
                {"tube_euid": tube_1, "row": "A", "col": 2},
            ],
        },
    )
    assert duplicate_tube.status_code == 400
    assert "duplicate assignment tube_euid" in duplicate_tube.json()["detail"]

    duplicate_well = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={
            "mode": "directed",
            "assignments": [
                {"tube_euid": tube_1, "row": "A", "col": 1},
                {"tube_euid": tube_2, "row": "A", "col": 1},
            ],
        },
    )
    assert duplicate_well.status_code == 400
    assert "duplicate destination well" in duplicate_well.json()["detail"]


def test_directed_library_plate_with_index_and_run_set() -> None:
    client = _client()
    tube, _ = _create_filled_tube(client, suffix="library-directed")
    extraction = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={"mode": "auto", "tube_euids": [tube]},
    )
    assert extraction.status_code == 200, extraction.text
    source_well = extraction.json()["mappings"][0]["well_euid"]
    index_euid = _create_reagent_index(client, name="pytest sequencing index")

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        response = client.post(
            "/api/v1/lab-actions/seq-library-plates",
            json={
                "mode": "directed",
                "plate_name": "pytest directed library plate",
                "assignments": [
                    {
                        "source_well_euid": source_well,
                        "row": "C",
                        "col": 4,
                        "index_barcode": "ACGTACGT",
                        "index_euid": index_euid,
                        "data": {"cycles": 8},
                    }
                ],
                "create_run_set": True,
                "run_set": {"name": "pytest library run set"},
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["run_set_euid"]
    assert payload["mappings"][0]["well_name"] == "C4"
    assert payload["mappings"][0]["index_barcode"] == "ACGTACGT"
    assert payload["mappings"][0]["index_euid"] == index_euid

    duplicate_destination = client.post(
        "/api/v1/lab-actions/seq-library-plates",
        json={
            "mode": "directed",
            "assignments": [
                {"source_well_euid": source_well, "row": "A", "col": 1},
                {"source_well_euid": source_well, "row": "A", "col": 1},
            ],
        },
    )
    assert duplicate_destination.status_code == 400
    assert "duplicate destination well" in duplicate_destination.json()["detail"]


def test_pool_existing_tube_pool_from_pool_and_seq_run_links() -> None:
    client = _client()
    tube, _ = _create_filled_tube(client, suffix="pool-existing")
    extraction = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={"mode": "auto", "tube_euids": [tube]},
    )
    assert extraction.status_code == 200, extraction.text
    library = client.post(
        "/api/v1/lab-actions/seq-library-plates",
        json={
            "mode": "plate_1_to_1",
            "source_plate_euid": extraction.json()["plate_euid"],
        },
    )
    assert library.status_code == 200, library.text
    library_content = library.json()["mappings"][0]["library_content_euid"]

    existing_pool_tube = _create_object(
        client,
        category="container",
        type_name="tube",
        subtype="tube-generic-10ml",
        name="pytest existing pool tube",
    )["euid"]
    first_pool = client.post(
        "/api/v1/lab-actions/seq-library-pools",
        json={
            "input_euids": [library_content],
            "pool_tube_euid": existing_pool_tube,
            "platform": "ILMN",
            "pool_name": "pytest first pool",
            "create_run_set": True,
        },
    )
    assert first_pool.status_code == 200, first_pool.text
    first_payload = first_pool.json()
    assert first_payload["pool_tube_euid"] == existing_pool_tube
    assert first_payload["new_container_euids"] == []
    assert first_payload["run_set_euid"]

    second_pool = client.post(
        "/api/v1/lab-actions/seq-library-pools",
        json={
            "input_euids": [first_payload["pool_tube_euid"]],
            "platform": "ILMN",
            "pool_name": "pytest pool from pool",
        },
    )
    assert second_pool.status_code == 200, second_pool.text
    assert second_pool.json()["member_euids"] == [first_payload["pool_content_euid"]]

    duplicate_inputs = client.post(
        "/api/v1/lab-actions/seq-library-pools",
        json={
            "input_euids": [library_content, library_content],
            "platform": "ILMN",
        },
    )
    assert duplicate_inputs.status_code == 400
    assert "duplicate input_euids" in duplicate_inputs.json()["detail"]

    instrument_euid = _create_instrument(client, name="pytest novaseq")
    reagent_euid = _create_reagent_index(client, name="pytest run reagent")
    seq_run = client.post(
        "/api/v1/lab-actions/seq-runs",
        json={
            "pool_tube_euid": second_pool.json()["pool_tube_euid"],
            "platform": "ILMN",
            "operator": "pytest@example.com",
            "instrument_euid": instrument_euid,
            "machine": "NovaSeq 6000",
            "flowcell_barcode": "FLOWCELL-LINKS",
            "reagent_euids": [reagent_euid],
            "status": "running",
            "metadata": {"purpose": "link coverage"},
        },
    )
    assert seq_run.status_code == 200, seq_run.text
    assert seq_run.json()["status"] == "running"


def test_lab_action_schema_validation_edges() -> None:
    client = _client()
    bad_auto = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={
            "mode": "auto",
            "tube_euids": ["Z-BCT-1"],
            "assignments": [{"tube_euid": "Z-BCT-2", "row": "A", "col": 1}],
        },
    )
    assert bad_auto.status_code == 422

    bad_directed = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={"mode": "directed", "tube_euids": ["Z-BCT-1"]},
    )
    assert bad_directed.status_code == 422

    bad_library = client.post(
        "/api/v1/lab-actions/seq-library-plates",
        json={"mode": "plate_1_to_1"},
    )
    assert bad_library.status_code == 422

    too_many_prints = client.post(
        "/api/v1/lab-actions/print-euids",
        json={
            "euids": [f"Z-BCT-{index}" for index in range(501)],
            "lab": "SSF",
            "printer_id": "pytest-printer",
            "label_zpl_style": "euid",
        },
    )
    assert too_many_prints.status_code == 422


def test_qc_plate_data_sets_and_pool_from_well_and_tube() -> None:
    client = _client()
    tube_1, _ = _create_filled_tube(client, suffix="qc-a")
    tube_2, _ = _create_filled_tube(client, suffix="qc-b")

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        extraction = client.post(
            "/api/v1/lab-actions/extraction-plates",
            json={
                "mode": "auto",
                "tube_euids": [tube_1],
                "plate_name": "pytest spreadsheet extraction plate",
            },
        )
    assert extraction.status_code == 200, extraction.text
    extraction_payload = extraction.json()
    source_well = extraction_payload["mappings"][0]["well_euid"]

    qc = client.post(
        "/api/v1/lab-actions/extraction-qc-plates",
        json={
            "source_plate_euid": extraction_payload["plate_euid"],
            "qc_plate_name": "pytest extraction QC plate",
            "assignments": [
                {
                    "source_well_euid": source_well,
                    "qc_row": "A",
                    "qc_col": 1,
                    "result": "pass",
                    "status": "recorded",
                    "data": {"concentration_ng_ul": 12.3},
                }
            ],
        },
    )
    assert qc.status_code == 200, qc.text
    qc_payload = qc.json()
    assert qc_payload["qc_plate_euid"]
    assert qc_payload["mappings"][0]["result"] == "pass"
    assert qc_payload["mappings"][0]["data_euid"]

    data = client.post(
        "/api/v1/lab-actions/plate-well-data",
        json={
            "data_template_code": "data/operation/extraction-qc/1.0/",
            "records": [
                {
                    "plate_euid": extraction_payload["plate_euid"],
                    "row": "A",
                    "col": 1,
                    "target": "content",
                    "data": {"a260_280": 1.82},
                }
            ],
        },
    )
    assert data.status_code == 200, data.text
    assert data.json()["mappings"][0]["data_euid"]

    lab_set = client.post(
        "/api/v1/lab-actions/sets",
        json={
            "name": "pytest extraction set",
            "members": [extraction_payload["plate_euid"], qc_payload["qc_plate_euid"]],
            "external_members": ["external-reagent-lot-1"],
        },
    )
    assert lab_set.status_code == 200, lab_set.text
    set_euid = lab_set.json()["set_euid"]
    add_members = client.post(
        f"/api/v1/lab-actions/sets/{set_euid}/members",
        json={"members": [tube_2], "external_members": ["operator-note-1"]},
    )
    assert add_members.status_code == 200, add_members.text
    fetched = client.get(f"/api/v1/lab-actions/sets/{set_euid}")
    assert fetched.status_code == 200
    assert tube_2 in fetched.json()["members"]
    assert "operator-note-1" in fetched.json()["external_members"]

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        pool = client.post(
            "/api/v1/lab-actions/seq-library-pools",
            json={
                "input_euids": [source_well, tube_2],
                "platform": "ILMN",
                "pool_name": "pytest well plus tube pool",
            },
        )
    assert pool.status_code == 200, pool.text
    assert len(pool.json()["member_euids"]) == 2


def _minimal_xlsx(sheet_name: str, rows: list[list[str | None]]) -> bytes:
    def cell_ref(row_index: int, col_index: int) -> str:
        col = ""
        value = col_index
        while value:
            value, remainder = divmod(value - 1, 26)
            col = chr(65 + remainder) + col
        return f"{col}{row_index}"

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            if value is None:
                continue
            cells.append(
                f'<c r="{cell_ref(row_index, col_index)}" t="inlineStr"><is><t>{value}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            "</Types>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def test_spreadsheet_import_csv_and_xlsx_preview() -> None:
    client = _client()
    tube, _ = _create_filled_tube(client, suffix="spreadsheet")
    csv_bytes = (
        "tube_euid,row,col,plate_name\n"
        f"{tube},A,1,pytest upload extraction plate\n"
    ).encode()
    dry_run = client.post(
        "/api/v1/lab-actions/spreadsheet-import",
        params={"dry_run": "true"},
        files={"file": ("extraction.csv", csv_bytes, "text/csv")},
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["actions"][0]["action"] == "extraction_plate"
    assert dry_run.json()["actions"][0]["request"]["mode"] == "directed"

    with patch(
        "bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None
    ):
        execute = client.post(
            "/api/v1/lab-actions/spreadsheet-import",
            params={"dry_run": "false"},
            files={"file": ("extraction.csv", csv_bytes, "text/csv")},
        )
    assert execute.status_code == 200, execute.text
    assert execute.json()["actions"][0]["result"]["plate_euid"]

    workbook = _minimal_xlsx(
        "Transfer",
        [
            [],
            [],
            ["SOURCE CONTAINER(s)", None, None, None, None, None, None, None, None, "DESTINATION CONTAINER(s)"],
            ["Container EUID", "Container Template EUID", "Continer Cat/Type/Subtype"],
            ["BCT-EXAMPLE", "container/tube/tube-generic-10ml/1.0", "container/tube/generic"],
        ],
    )
    parsed = parse_workbook("container_interactions.xlsx", workbook)
    assert parsed[0].name == "Transfer"
    assert "container_euid" in parsed[0].headers
    preview = client.post(
        "/api/v1/lab-actions/spreadsheet-import",
        params={"dry_run": "true"},
        files={
            "file": (
                "container_interactions.xlsx",
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["actions"][0]["action"] == "container_interaction_preview"


def _upload_csv(client: TestClient, csv_text: str, *, dry_run: bool = False):
    return client.post(
        "/api/v1/lab-actions/spreadsheet-import",
        params={"dry_run": str(dry_run).lower()},
        files={"file": ("lab_action.csv", csv_text.encode(), "text/csv")},
    )


def test_spreadsheet_import_executes_each_lab_action_sheet_shape() -> None:
    client = _client()
    tube, _ = _create_filled_tube(client, suffix="upload-flow")
    extraction = client.post(
        "/api/v1/lab-actions/extraction-plates",
        json={"mode": "auto", "tube_euids": [tube]},
    )
    assert extraction.status_code == 200, extraction.text
    extraction_payload = extraction.json()
    source_well = extraction_payload["mappings"][0]["well_euid"]

    qc_csv = (
        "source_well_euid,qc_row,qc_col,result,status,data_concentration_ng_ul\n"
        f"{source_well},A,1,pass,recorded,11.2\n"
    )
    qc = _upload_csv(client, qc_csv)
    assert qc.status_code == 200, qc.text
    qc_action = qc.json()["actions"][0]
    assert qc_action["action"] == "extraction_qc"
    assert qc_action["result"]["mappings"][0]["result"] == "pass"

    library_csv = (
        "source_well_euid,row,col,index_barcode,data_cycles\n"
        f"{source_well},A,1,ACGTACGT,8\n"
    )
    library = _upload_csv(client, library_csv)
    assert library.status_code == 200, library.text
    library_action = library.json()["actions"][0]
    assert library_action["action"] == "seq_library_plate"
    library_content = library_action["result"]["mappings"][0]["library_content_euid"]

    pool_csv = (
        "input_euids,platform,pool_name,pool_batch\n"
        f"{library_content},ILMN,pytest upload pool,batch-1\n"
    )
    pool = _upload_csv(client, pool_csv)
    assert pool.status_code == 200, pool.text
    pool_action = pool.json()["actions"][0]
    assert pool_action["action"] == "seq_pool"
    pool_result = pool_action["result"]

    run_csv = (
        "pool_tube_euid,pool_content_euid,platform,operator,flowcell_barcode,status,run_batch\n"
        f"{pool_result['pool_tube_euid']},{pool_result['pool_content_euid']},ILMN,pytest@example.com,FLOWCELL-UPLOAD,created,batch-1\n"
    )
    run = _upload_csv(client, run_csv)
    assert run.status_code == 200, run.text
    run_action = run.json()["actions"][0]
    assert run_action["action"] == "seq_run_set"
    assert run_action["result"]["set_euid"]

    set_csv = (
        "name,members,external_members,status,set_note\n"
        f"pytest upload set,{extraction_payload['plate_euid']};{pool_result['pool_tube_euid']},lot:123,created,upload\n"
    )
    lab_set = _upload_csv(client, set_csv)
    assert lab_set.status_code == 200, lab_set.text
    set_action = lab_set.json()["actions"][0]
    assert set_action["action"] == "sets"
    assert set_action["result"][0]["set_euid"]

    data_csv = (
        "well_euid,data_template_code,target,name,annotation_value,metric_a260_280\n"
        f"{source_well},data/operation/extraction-qc/1.0/,content,pytest uploaded data,ok,1.82\n"
    )
    data = _upload_csv(client, data_csv)
    assert data.status_code == 200, data.text
    data_action = data.json()["actions"][0]
    assert data_action["action"] == "plate_well_data"
    assert data_action["result"]["mappings"][0]["data_euid"]

    bad_extension = client.post(
        "/api/v1/lab-actions/spreadsheet-import",
        files={"file": ("lab_action.txt", b"not,csv", "text/plain")},
    )
    assert bad_extension.status_code == 400
    assert "must be .csv or .xlsx" in bad_extension.json()["detail"]


def test_lab_actions_gui_renders_upload_qc_and_set_controls() -> None:
    client = _client()
    response = client.get("/lab-actions")
    assert response.status_code == 200, response.text
    assert "Extraction QC Plate" in response.text
    assert "Spreadsheet Upload" in response.text
    assert "Manage Sets" in response.text
    assert 'data-action="upload-spreadsheet"' in response.text
