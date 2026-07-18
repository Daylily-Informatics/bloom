#!/usr/bin/env python3
"""Generate deterministic, create-only Bjuice Bloom backfill plans."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ILLUMINA_SOURCE = Path(
    "/Users/jmajor/projects/lsmc/docs/plans/"
    "20260623T111859Z_last10_completion_to_100_artifacts/"
    "ilmn_20260618_fastq_callers/SampleSheet.csv"
)
DEFAULT_ONT_SOURCE = Path(
    "/Users/jmajor/projects/lsmc/docs/plans/"
    "20260625T022718Z_ont_barcode_to_sample_map_from_drive.tsv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "docs"
    / "plans"
    / "20260718T044845Z_bjuice_atlas_bloom_templates_backfill_artifacts"
)

SEQUENCING_INDEX_TEMPLATE = {
    "category": "material",
    "type": "reagent",
    "subtype": "sequencing-index",
    "version": "1.0",
}

EQUIPMENT_TEMPLATE_CATALOG = (
    ("generic", "1.0", "Generic Sequencer", "", "", "neutral"),
    (
        "novaseq-6000",
        "1.1",
        "Illumina NovaSeq 6000",
        "Illumina",
        "NovaSeq 6000",
        "current",
    ),
    (
        "novaseq-x-series",
        "1.0",
        "Illumina NovaSeq X Series",
        "Illumina",
        "NovaSeq X Series",
        "current",
    ),
    (
        "ont-minion",
        "1.1",
        "Oxford Nanopore MinION",
        "Oxford Nanopore Technologies",
        "MinION",
        "current",
    ),
    (
        "ont-promethion",
        "1.0",
        "Oxford Nanopore PromethION",
        "Oxford Nanopore Technologies",
        "PromethION",
        "current",
    ),
    (
        "ultima-ug-100",
        "1.0",
        "Ultima Genomics UG 100",
        "Ultima Genomics",
        "UG 100",
        "current",
    ),
    (
        "ultima-ug-200-series",
        "1.0",
        "Ultima Genomics UG200 Series",
        "Ultima Genomics",
        "UG200 Series",
        "current",
    ),
    ("pacbio-revio", "1.0", "PacBio Revio", "PacBio", "Revio", "current"),
    ("pacbio-vega", "1.0", "PacBio Vega", "PacBio", "Vega", "current"),
    (
        "pacbio-sequel-ii",
        "1.0",
        "PacBio Sequel II",
        "PacBio",
        "Sequel II",
        "legacy",
    ),
    (
        "pacbio-sequel-iie",
        "1.0",
        "PacBio Sequel IIe",
        "PacBio",
        "Sequel IIe",
        "legacy",
    ),
    ("pacbio-onso", "1.0", "PacBio Onso", "PacBio", "Onso", "legacy"),
)

MERIDIAN_EUID_RE = re.compile(r"\bM-[A-Z0-9]+-[A-Z0-9]+\b")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def parse_illumina_samplesheet(
    path: Path,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header: dict[str, str] = {}
    section = ""
    data_lines: list[str] = []
    for line in lines:
        section_match = re.fullmatch(r"\[([^]]+)](?:,)?", line)
        if section_match:
            section = section_match.group(1)
            continue
        if not line:
            continue
        if section == "Header":
            key, value = next(csv.reader([line]))[:2]
            header[key] = value
        elif section == "BCLConvert_Data":
            data_lines.append(line)

    rows = list(csv.DictReader(data_lines))
    required = {"Sample_ID", "Index", "Index2"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Illumina SampleSheet lacks BCLConvert_Data index columns")
    if len(rows) != 21:
        raise ValueError(f"expected 21 Illumina index pairs, found {len(rows)}")

    normalized = [
        {
            "sample_id": row["Sample_ID"].strip(),
            "i7_sequence": row["Index"].strip().upper(),
            "i5_sequence": row["Index2"].strip().upper(),
        }
        for row in rows
    ]
    pairs = {(row["i7_sequence"], row["i5_sequence"]) for row in normalized}
    if len(pairs) != len(normalized):
        raise ValueError("Illumina SampleSheet contains duplicate i7/i5 pairs")
    return header, normalized


def parse_ont_map(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    expected_barcodes = [f"barcode{number:02d}" for number in range(1, 17)]
    by_barcode = {row["barcode"].strip().lower(): row for row in rows}
    if sorted(by_barcode) != expected_barcodes:
        raise ValueError("ONT map must contain exactly barcode01 through barcode16")
    return [
        {
            "barcode_name": barcode,
            "sample_id": by_barcode[barcode]["sample_id"].strip(),
            "ont_library_id": by_barcode[barcode]["ont_library_id"].strip(),
            "set_id": by_barcode[barcode]["set_id"].strip(),
        }
        for barcode in expected_barcodes
    ]


def build_artifacts(illumina_source: Path, ont_source: Path) -> dict[str, Any]:
    header, illumina_rows = parse_illumina_samplesheet(illumina_source)
    ont_rows = parse_ont_map(ont_source)

    run_name = header.get("RunName", "")
    orientation = header.get("IndexOrientation", "")
    if not run_name or not orientation:
        raise ValueError("Illumina SampleSheet lacks RunName or IndexOrientation")

    illumina_plans = []
    for row in illumina_rows:
        sample_id = row["sample_id"]
        i7 = row["i7_sequence"]
        i5 = row["i5_sequence"]
        illumina_plans.append(
            {
                "idempotency_key": f"bjuice:ilmn-index-pair:{run_name}:{sample_id}:{i7}:{i5}",
                "mutation_class": "create_only",
                "object_kind": "illumina_dual_index_pair",
                "on_conflict": "BLOCK",
                "on_exact_match": "REUSE",
                "operation": "CREATE",
                "properties": {
                    "i5_sequence": i5,
                    "i7_sequence": i7,
                    "index_barcode": i7,
                    "index_orientation": orientation,
                    "index_sequence": i7,
                    "index_set": run_name,
                    "name": f"{run_name}:{sample_id}:i7+i5",
                    "platform": "ILMN",
                    "sample_id": sample_id,
                    "sequence_known": True,
                },
                "schema": "bloom.create_plan.v1",
                "template": SEQUENCING_INDEX_TEMPLATE,
            }
        )

    ont_plans = []
    for row in ont_rows:
        barcode = row["barcode_name"]
        ont_plans.append(
            {
                "idempotency_key": f"bjuice:ont-barcode:SQK-NBD114-24:{barcode}",
                "mutation_class": "create_only",
                "object_kind": "ont_barcode_index",
                "on_conflict": "BLOCK",
                "on_exact_match": "REUSE",
                "operation": "CREATE",
                "properties": {
                    "barcode_name": barcode,
                    "index_barcode": barcode,
                    "index_name": barcode,
                    "index_sequence": "",
                    "index_set": "SQK-NBD114-24",
                    "name": f"SQK-NBD114-24:{barcode}",
                    "ont_library_id": row["ont_library_id"],
                    "platform": "ONT",
                    "sample_id": row["sample_id"],
                    "sequence_known": False,
                    "set_id": row["set_id"],
                },
                "schema": "bloom.create_plan.v1",
                "template": SEQUENCING_INDEX_TEMPLATE,
            }
        )

    equipment_catalog = [
        {
            "bstatus": "active",
            "category": "equipment",
            "instance_polymorphic_identity": "equipment_instance",
            "instance_prefix": "BEQ",
            "is_singleton": False,
            "lifecycle_status": lifecycle_status,
            "manufacturer": manufacturer,
            "model_family": model_family,
            "name": name,
            "polymorphic_discriminator": "equipment_template",
            "subtype": subtype,
            "type": "sequencers",
            "version": version,
        }
        for subtype, version, name, manufacturer, model_family, lifecycle_status in EQUIPMENT_TEMPLATE_CATALOG
    ]

    equipment_instances = [
        {
            "idempotency_key": "bjuice:equipment:instrument-id:LH01106",
            "lookup": {"instrument_id": "LH01106"},
            "mutation_class": "create_only",
            "object_kind": "sequencing_instrument",
            "on_conflict": "BLOCK",
            "on_exact_match": "REUSE",
            "operation": "CREATE",
            "properties": {
                "instrument_id": "LH01106",
                "manufacturer": "Illumina",
                "model": "",
                "model_family": "NovaSeq X Series",
                "name": "LH01106",
                "serial_number": "LH01106",
            },
            "schema": "bloom.create_plan.v1",
            "template": {
                "category": "equipment",
                "type": "sequencers",
                "subtype": "novaseq-x-series",
                "version": "1.0",
            },
        },
        {
            "idempotency_key": "bjuice:equipment:instrument-id:PCA100",
            "lookup": {"instrument_id": "PCA100"},
            "mutation_class": "create_only",
            "object_kind": "sequencing_instrument",
            "on_conflict": "BLOCK",
            "on_exact_match": "REUSE",
            "operation": "CREATE",
            "properties": {
                "instrument_id": "PCA100",
                "manufacturer": "Oxford Nanopore Technologies",
                "model": "",
                "model_family": "PromethION",
                "name": "PCA100",
                "serial_number": "PCA100",
            },
            "schema": "bloom.create_plan.v1",
            "template": {
                "category": "equipment",
                "type": "sequencers",
                "subtype": "ont-promethion",
                "version": "1.0",
            },
        },
    ]

    lineage_audit = {
        "allowed_relationship_types": ["beta_used_instrument", "run_uses_instrument"],
        "expected_instruments": ["LH01106", "PCA100"],
        "mutation_allowed": False,
        "operation": "READ_ONLY_AUDIT",
        "required_receipts": [
            "real run-set EUIDs returned by Bloom",
            "real equipment EUIDs returned by Bloom",
            "current active instrument lineage per run set",
            "relationship EUIDs for any incorrect active links",
        ],
        "schema": "bloom.equipment_lineage_audit_plan.v1",
        "status": "BLOCKED",
        "unblock_condition": "Read current production lineage through supported Bloom APIs and review exact EUID-scoped diff.",
    }
    lineage_forward = {
        "before_state_hashes": [],
        "executable_operations": [],
        "expected_change_count": None,
        "schema": "bloom.equipment_lineage_forward_skeleton.v1",
        "status": "BLOCKED",
        "unblock_condition": "Populate only from approved read-only audit receipts containing real EUIDs and current lineage.",
    }
    lineage_rollback = {
        "before_state_hashes": [],
        "executable_operations": [],
        "expected_change_count": None,
        "schema": "bloom.equipment_lineage_rollback_skeleton.v1",
        "status": "BLOCKED",
        "unblock_condition": "Generate exact inverse from the reviewed forward manifest; do not invent identifiers.",
    }

    return {
        "bloom_bjuice_equipment_instance_create_plan.jsonl": equipment_instances,
        "bloom_equipment_lineage_audit_plan.json": lineage_audit,
        "bloom_equipment_lineage_forward_skeleton.json": lineage_forward,
        "bloom_equipment_lineage_rollback_skeleton.json": lineage_rollback,
        "bloom_equipment_template_catalog.json": equipment_catalog,
        "bloom_illumina_index_pair_create_plan.jsonl": illumina_plans,
        "bloom_ont_barcode_create_plan.jsonl": ont_plans,
    }


def generate(illumina_source: Path, ont_source: Path, output_dir: Path) -> None:
    if not illumina_source.is_file():
        raise FileNotFoundError(f"Illumina source does not exist: {illumina_source}")
    if not ont_source.is_file():
        raise FileNotFoundError(f"ONT source does not exist: {ont_source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir = output_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    illumina_snapshot = inputs_dir / "illumina_samplesheet.csv"
    ont_snapshot = inputs_dir / "ont_barcode_to_sample_map.tsv"
    if illumina_source.resolve() != illumina_snapshot.resolve():
        shutil.copyfile(illumina_source, illumina_snapshot)
    if ont_source.resolve() != ont_snapshot.resolve():
        shutil.copyfile(ont_source, ont_snapshot)

    artifacts = build_artifacts(illumina_source, ont_source)
    for name, payload in artifacts.items():
        path = output_dir / name
        if name.endswith(".jsonl"):
            _write_jsonl(path, payload)
        else:
            _write_json(path, payload)

    checksums = {name: _sha256(output_dir / name) for name in sorted(artifacts)}
    summary = {
        "artifact_checksums_sha256": checksums,
        "counts": {
            "bjuice_equipment_instance_create_plans": 2,
            "equipment_templates": len(EQUIPMENT_TEMPLATE_CATALOG),
            "illumina_dual_index_pairs": 21,
            "ont_barcode_indexes": 16,
        },
        "input_checksums_sha256": {
            "illumina_samplesheet.csv": _sha256(illumina_snapshot),
            "ont_barcode_to_sample_map.tsv": _sha256(ont_snapshot),
        },
        "mutation_contract": {
            "create_only": True,
            "direct_sql": False,
            "invented_euids": False,
            "update_or_delete": False,
        },
        "schema": "bloom.bjuice_backfill_manifest_summary.v1",
        "status": {
            "create_plans": "READY_FOR_REVIEW",
            "equipment_lineage_repair": "BLOCKED_PENDING_REAL_EUID_AUDIT",
        },
    }
    _write_json(output_dir / "bloom_write_manifest_summary.json", summary)

    generated_text = "".join(
        path.read_text(encoding="utf-8") for path in sorted(output_dir.glob("bloom_*"))
    )
    if MERIDIAN_EUID_RE.search(generated_text):
        raise ValueError("generated artifacts contain an unissued Meridian-style EUID")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--illumina-source", type=Path, default=DEFAULT_ILLUMINA_SOURCE)
    parser.add_argument("--ont-source", type=Path, default=DEFAULT_ONT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    generate(args.illumina_source, args.ont_source, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
