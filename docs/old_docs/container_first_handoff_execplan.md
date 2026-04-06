# Container-First Atlas to Bloom Handoff Execution Plan

Status: in_progress  
Date: 2026-03-08

## Objective
Align accepted-material ingestion so queue ingress and cross-system linkage are container-first while preserving specimen lineage and patient linkage.

## Change Groups

1. Atlas bridge and external-object graph updates
- Queue accepted material by `container_euid`.
- Persist container mapping before specimen mapping.
- Keep container relations to TRF/Test/TestFulfillmentItem + Shipment/TestKit.
- Keep specimen relations to Patient + containment only.

2. Bloom accepted-material behavior updates
- Resolve/create container before specimen creation.
- Attach fulfillment-item reference links to container.
- Attach patient-only reference link to specimen.
- Add patient EUID to accepted-material Atlas context contract.
- Add queue-resolution fallback: specimen can resolve queue from containing container.

3. Contract/docs updates
- Document container-targeted ingress queue behavior.
- Document specimen mapping policy: patient + containment.
- Document accepted-material context shape change including patient EUID.

4. Tests
- Atlas tests for queue target and relation graph policy.
- Bloom tests for container-first registration, link placement, and queue fallback.
- At least one end-to-end queue flow updated for container ingress.

## Acceptance Checks
- Atlas accepted-material handoff calls Bloom queue endpoint with `container_euid`.
- Atlas specimen external-object mapping has no test/test-fulfillment-item relations.
- Bloom accepted-material creation stores fulfillment-item refs on container and patient ref on specimen.
- Bloom extraction succeeds when only container has ingress queue membership.
- Resolver and downstream beta flow remain unchanged.

## Breaking-Change Notes
- `POST /api/v1/external/atlas/beta/materials` accepted-material context now carries Atlas patient EUID.
- Specimen external-object relation semantics changed: no direct test/test-fulfillment-item relation projection.
