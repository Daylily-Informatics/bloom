"""Retired workflow compatibility surface for queue-only Bloom beta."""

from __future__ import annotations

from bloom_lims.domain.base import BloomObj


class BloomWorkflow(BloomObj):
    """Retired workflow alias kept importable during queue-only cleanup."""


class BloomWorkflowStep(BloomObj):
    """Retired workflow-step alias kept importable during queue-only cleanup."""


__all__ = ["BloomWorkflow", "BloomWorkflowStep"]
