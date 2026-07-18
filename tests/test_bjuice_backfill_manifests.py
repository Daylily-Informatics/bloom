"""Deterministic and safety contracts for Bjuice backfill manifests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = (
    PROJECT_ROOT
    / "docs"
    / "plans"
    / "20260718T044845Z_bjuice_atlas_bloom_templates_backfill_artifacts"
)
GENERATOR_PATH = PROJECT_ROOT / "scripts" / "generate_bjuice_backfill_manifests.py"
MERIDIAN_EUID_RE = re.compile(r"\bM-[A-Z0-9]+-[A-Z0-9]+\b")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "bjuice_manifest_generator", GENERATOR_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_create_plans_have_exact_source_counts_and_index_contracts() -> None:
    illumina = _jsonl(ARTIFACT_DIR / "bloom_illumina_index_pair_create_plan.jsonl")
    ont = _jsonl(ARTIFACT_DIR / "bloom_ont_barcode_create_plan.jsonl")

    assert len(illumina) == 21
    assert (
        len(
            {
                (row["properties"]["i7_sequence"], row["properties"]["i5_sequence"])
                for row in illumina
            }
        )
        == 21
    )
    assert len({row["idempotency_key"] for row in illumina}) == 21
    assert {row["properties"]["platform"] for row in illumina} == {"ILMN"}
    assert all(row["properties"]["sequence_known"] is True for row in illumina)

    assert len(ont) == 16
    assert [row["properties"]["barcode_name"] for row in ont] == [
        f"barcode{number:02d}" for number in range(1, 17)
    ]
    assert len({row["idempotency_key"] for row in ont}) == 16
    assert {row["properties"]["platform"] for row in ont} == {"ONT"}
    assert all(row["properties"]["sequence_known"] is False for row in ont)
    assert all(row["properties"]["index_sequence"] == "" for row in ont)


def test_only_reviewed_bjuice_equipment_instances_are_planned() -> None:
    rows = _jsonl(ARTIFACT_DIR / "bloom_bjuice_equipment_instance_create_plan.jsonl")

    assert [row["properties"]["instrument_id"] for row in rows] == ["LH01106", "PCA100"]
    assert [row["template"]["subtype"] for row in rows] == [
        "novaseq-x-series",
        "ont-promethion",
    ]


def test_all_object_plans_are_create_only_and_contain_no_invented_euids() -> None:
    plan_files = sorted(ARTIFACT_DIR.glob("*create_plan.jsonl"))
    assert plan_files
    for plan_file in plan_files:
        rows = _jsonl(plan_file)
        assert rows
        for row in rows:
            assert row["operation"] == "CREATE"
            assert row["mutation_class"] == "create_only"
            assert row["idempotency_key"]
            assert row["on_exact_match"] == "REUSE"
            assert row["on_conflict"] == "BLOCK"
            assert not MERIDIAN_EUID_RE.search(json.dumps(row, sort_keys=True))

    all_artifacts = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(ARTIFACT_DIR.glob("bloom_*"))
    )
    assert '"operation": "UPDATE"' not in all_artifacts
    assert '"operation": "DELETE"' not in all_artifacts
    assert not MERIDIAN_EUID_RE.search(all_artifacts)


def test_lineage_plans_remain_blocked_until_real_euids_are_audited() -> None:
    audit = json.loads(
        (ARTIFACT_DIR / "bloom_equipment_lineage_audit_plan.json").read_text(
            encoding="utf-8"
        )
    )
    forward = json.loads(
        (ARTIFACT_DIR / "bloom_equipment_lineage_forward_skeleton.json").read_text(
            encoding="utf-8"
        )
    )
    rollback = json.loads(
        (ARTIFACT_DIR / "bloom_equipment_lineage_rollback_skeleton.json").read_text(
            encoding="utf-8"
        )
    )

    assert audit["operation"] == "READ_ONLY_AUDIT"
    assert audit["mutation_allowed"] is False
    assert audit["status"] == "BLOCKED"
    assert forward["status"] == "BLOCKED"
    assert rollback["status"] == "BLOCKED"
    assert forward["executable_operations"] == []
    assert rollback["executable_operations"] == []


def test_committed_artifacts_reproduce_from_captured_inputs(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.generate(
        ARTIFACT_DIR / "inputs" / "illumina_samplesheet.csv",
        ARTIFACT_DIR / "inputs" / "ont_barcode_to_sample_map.tsv",
        tmp_path,
    )

    expected_files = sorted(
        path.relative_to(ARTIFACT_DIR)
        for path in ARTIFACT_DIR.rglob("*")
        if path.is_file()
    )
    generated_files = sorted(
        path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()
    )
    assert generated_files == expected_files
    for relative_path in expected_files:
        assert (tmp_path / relative_path).read_bytes() == (
            ARTIFACT_DIR / relative_path
        ).read_bytes()


def test_summary_checksums_cover_every_generated_manifest() -> None:
    summary = json.loads(
        (ARTIFACT_DIR / "bloom_write_manifest_summary.json").read_text(encoding="utf-8")
    )

    assert summary["counts"] == {
        "bjuice_equipment_instance_create_plans": 2,
        "equipment_templates": 12,
        "illumina_dual_index_pairs": 21,
        "ont_barcode_indexes": 16,
    }
    assert summary["mutation_contract"] == {
        "create_only": True,
        "direct_sql": False,
        "invented_euids": False,
        "update_or_delete": False,
    }
    for name, checksum in summary["artifact_checksums_sha256"].items():
        assert _sha256(ARTIFACT_DIR / name) == checksum
