# Architecture Guidance

## Bloom Role

Bloom is the beta owner of material and wet-lab execution state.

Bloom owns:

- containers
- specimens
- plates and wells
- extraction outputs
- library prep outputs
- pools
- sequencing runs
- queue membership and queue-transition history

Bloom does not own accessioning or customer-facing order truth.

## Runtime Model

Bloom beta paths are queue-driven, not workflow-driven.

The supported beta queues are:

- `extraction_prod`
- `extraction_rnd`
- `post_extract_qc`
- `ilmn_lib_prep`
- `ont_lib_prep`
- `ilmn_seq_pool`
- `ont_seq_pool`
- `ilmn_start_seq_run`
- `ont_start_seq_run`

Queue movement is explicit. Material lineage is explicit. Atlas identity linkage is explicit.

## Integration Rules

- Atlas sends accepted material into Bloom through explicit APIs.
- Bloom stores Atlas linkage through external-object references.
- Bloom preserves lineage from specimen and container to run.
- Bloom resolves `run_euid + index_string` to Atlas tenant, order, and TRF.test EUIDs.
- Public APIs use EUIDs only.

## Non-Goals

Bloom beta paths must not depend on:

- workflow and workflow-step runtime orchestration
- legacy `do_action` API execution
- accessioning ownership
- hidden UUID-based cross-service joins
