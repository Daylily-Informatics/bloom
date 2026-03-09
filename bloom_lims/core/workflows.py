"""Retired workflow helpers kept importable while queue-only Bloom settles."""

from __future__ import annotations

from typing import Any

from bloom_lims.domain.workflows import BloomWorkflow, BloomWorkflowStep


class BloomWorkflowMixin:
    """Retired workflow mixin placeholder."""


class BloomWorkflowStepMixin:
    """Retired workflow-step mixin placeholder."""


def _retired(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Bloom workflow runtime is retired; use queue-driven beta APIs instead.")


create_workflow = _retired
create_workflow_step = _retired
get_workflow_by_euid = _retired
get_workflow_steps = _retired
advance_workflow = _retired


__all__ = [
    "BloomWorkflow",
    "BloomWorkflowStep",
    "BloomWorkflowMixin",
    "BloomWorkflowStepMixin",
    "create_workflow",
    "create_workflow_step",
    "get_workflow_by_euid",
    "get_workflow_steps",
    "advance_workflow",
]
