"""Sequencing-run template and schema contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bloom_lims.schemas.beta_lab import BetaRunCreateRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _minimal_run_payload(**overrides):
    payload = {
        "pool_euid": "BNP-POOL-1",
        "platform": "ILMN",
        "run_subtype": "illumina",
        "flowcell_id": "FLOW-1",
        "operator_start_datetime": "2026-05-20T06:00:00+00:00",
        "sequencing_end_datetime": "2026-05-20T14:00:00+00:00",
        "assignments": [
            {
                "lane": "1",
                "library_barcode": "IDX-1",
                "library_prep_output_euid": "BDP-LIB-1",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_sequencing_run_templates_are_shipped_for_tapdb_seed():
    template_pack = json.loads(
        (
            PROJECT_ROOT / "config" / "tapdb_templates" / "bloom" / "templates.json"
        ).read_text(encoding="utf-8")
    )
    templates = {
        (
            template["json_addl"].get("semantic_category"),
            template["type"],
            template["subtype"],
            template["version"],
        ): template
        for template in template_pack["templates"]
    }

    expected = {
        ("data", "sequencing_run", "illumina", "1.0"): ("ILMN", "BRM"),
        ("data", "sequencing_run", "ont", "1.0"): ("ONT", "BRN"),
        ("data", "sequencing_run", "ultima", "1.0"): ("Ultima", "BRT"),
        ("data", "sequencing_run", "completegenomics", "1.0"): (
            "CompleteGenomics",
            "BRC",
        ),
        ("data", "sequencing_run", "pacbio", "1.0"): ("PacBio", "BRP"),
    }
    for template_key, (platform, instance_prefix) in expected.items():
        template = templates[template_key]
        props = template["json_addl"]["properties"]
        assert template["category"] == instance_prefix
        assert template["instance_prefix"] == instance_prefix
        assert template["json_addl"]["semantic_category"] == "data"
        assert props["beta_kind"] == "sequencing_run"
        assert props["platform"] == platform
        assert props["run_subtype"] == template_key[2]
        assert "operator_start_datetime" in props
        assert "sequencing_end_datetime" in props
        assert "instrument_euid" in props


def test_run_schema_validates_subtype_platform_and_datetime_contract():
    expected = {
        "ILMN": "illumina",
        "ONT": "ont",
        "Ultima": "ultima",
        "PacBio": "pacbio",
        "CompleteGenomics": "completegenomics",
    }
    for platform, run_subtype in expected.items():
        run = BetaRunCreateRequest.model_validate(
            _minimal_run_payload(platform=platform, run_subtype=run_subtype)
        )
        assert run.platform == platform
        assert run.run_subtype == run_subtype

    with pytest.raises(ValidationError, match="platform=ONT requires run_subtype=ont"):
        BetaRunCreateRequest.model_validate(
            _minimal_run_payload(platform="ONT", run_subtype="illumina")
        )

    with pytest.raises(ValidationError, match="must include a timezone"):
        BetaRunCreateRequest.model_validate(
            _minimal_run_payload(operator_start_datetime="2026-05-20T06:00:00")
        )

    with pytest.raises(ValidationError, match="must not be before"):
        BetaRunCreateRequest.model_validate(
            _minimal_run_payload(
                operator_start_datetime="2026-05-20T15:00:00+00:00",
                sequencing_end_datetime="2026-05-20T14:00:00+00:00",
            )
        )
