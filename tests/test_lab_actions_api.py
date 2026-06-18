"""API coverage for Bloom lab actions."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
os.environ["BLOOM_OAUTH"] = "no"

from fastapi.testclient import TestClient

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

    sample_sheet = client.get(
        f"/api/v1/lab-actions/seq-runs/{run_payload['set_euid']}/samplesheet"
    )
    assert sample_sheet.status_code == 200, sample_sheet.text
    assert "[Header]" in sample_sheet.text
    assert f"RunSetEUID,{run_payload['set_euid']}" in sample_sheet.text
    assert "PYTEST-FLOWCELL" in sample_sheet.text
    for library_content in library_contents:
        assert library_content in sample_sheet.text


def test_lab_actions_validation_and_non_ilmn_samplesheet_rejection() -> None:
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
    assert sample_sheet.status_code == 400
    assert "only implemented for ILMN" in sample_sheet.json()["detail"]


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
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["printed"] == 3
    assert service.submit_print_job.call_count == 3

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
