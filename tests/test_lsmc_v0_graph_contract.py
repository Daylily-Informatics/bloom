from __future__ import annotations

from types import SimpleNamespace

import pytest

from bloom_lims.domain.v0_graph import attach_bloom_v0_edge, object_evidence


def test_attach_bloom_v0_edge_stores_metadata_under_properties():
    lineage = SimpleNamespace(json_addl={})

    attach_bloom_v0_edge(
        lineage,
        edge_type="HOLDS_MATERIAL",
        source_euid="Z-BCT-SRC",
        target_euid="Z-BNB-TGT",
        evidence_refs=[
            object_evidence("Z-BCT-SRC", role="container"),
            object_evidence("Z-BNB-TGT", role="material"),
        ],
        correlation_id="bloom:test:correlation",
        causation_id="bloom:test:causation",
    )

    v0_edge = lineage.json_addl["properties"]["v0_edge"]
    assert v0_edge["contract"] == "LSMC_V0"
    assert v0_edge["edge_type"] == "HOLDS_MATERIAL"
    assert v0_edge["source_euid"] == "Z-BCT-SRC"
    assert v0_edge["target_euid"] == "Z-BNB-TGT"


def test_attach_bloom_v0_edge_rejects_missing_evidence():
    with pytest.raises(ValueError, match="evidence_refs"):
        attach_bloom_v0_edge(
            SimpleNamespace(json_addl={}),
            edge_type="MATERIAL_FROM_SUBJECT",
            source_euid="Z-BNB-SRC",
            target_euid="Z-AGX-TGT",
            evidence_refs=[],
            correlation_id="bloom:test:correlation",
            causation_id="bloom:test:causation",
        )
