# Bloom Queue Refactor Execution Plan

## Goal

Refactor Bloom into the authoritative beta owner of material objects and queue-driven wet-lab execution state, without relying on the legacy workflow/workflow-step runtime for active beta paths.

## Current Findings

- `bloom_lims/core/action_execution.py` still routes through legacy object/workflow executors and legacy required-field extraction.
- `bloom_lims/domain/base.py` still contains active `do_action_*` plumbing and grouped action payload assumptions.
- `bloom_lims/domain/workflows.py` still performs queue routing through workflow-step objects.
- `bloom_lims/domain/external_specimens.py` still uses broad scans for reference and idempotency lookup paths.
- No resolver currently exists for `run_euid + index_string`.

## Decisions

- The beta queue model will be explicit and first-class; it will not be represented as active workflow/workflow-step runtime.
- Bloom will preserve material lineage with `generic_instance_lineage`.
- Atlas links will stay explicit through external-object link instances rather than embedded private identifiers.
- Public beta APIs will be EUID-only.
- Existing workflow code may remain on disk temporarily, but it must not remain on the active beta-critical path.

## Implementation Outline

1. Add queue-domain services for beta queue definition, membership, transition, and lineage-aware movement.
2. Add sequencing-run and run-index resolution services that return Atlas order and test-order EUIDs.
3. Keep external specimen creation as the Atlas entry point for accepted material, but rewrite its lookup paths to avoid broad scans.
4. Remove workflow router exposure from the active beta API surface and stop documenting workflow/workflow-step as the primary model.
5. Replace or isolate legacy action execution paths so beta queue transitions use modern TapDB-backed execution only.

## Required Validation

- create/register container plus specimen with Atlas external links
- place accepted material into an extraction queue
- map extraction output into plate/well lineage
- advance through post-extract QC and lib prep queue selection
- create pool and sequencing run
- resolve `run_euid + index_string`
- confirm public API payloads do not expose private UUIDs
