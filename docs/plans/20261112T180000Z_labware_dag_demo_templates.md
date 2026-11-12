# Current continuation state

Objective: save the all-new Bloom labware demonstration template pack in the normal seed directory, load it through TapDB, create the requested DAG examples, and document real node and edge EUIDs.

User authority: November 12 request authorizes new clean templates and synthetic demo objects, then explicitly approves the TapDB CLI loader and asks to commit/save templates for future deployments. Existing templates remain untouched. No tests, build, release, PR, merge, credentials, or runtime configuration changes are authorized.

Source: existing clean branch `codex/bloom-ursa-api-guide-20261030`. Live Bloom day is 10.1.1 at e7821bef2851f0c5b8e54d1871c9396609f25e64 with TapDB 11.0.2. This branch contains the deployed revision plus a documentation commit. Committing a pack does not deploy it.

Pack: `config/tapdb_templates/bloom/labware_dag_demo_20261112.json`, 26 insert-only definitions with subtype prefix `demo-20261112-`. Loaded by the normal Bloom seed-directory discovery when this revision is included in a deployment. Seeding definitions does not instantiate the demonstration cohort automatically.

Live status: the native template builder accepted validation, but Save failed with `Capture requires an active REPEATABLE READ or SERIALIZABLE transaction`. The approved CLI loader then stopped at its operator preflight with `RuntimePrincipalError`. Its explicit runtime target has no operator configuration. No new template was committed by either attempt. Awaiting the existing operator configuration or authority to prepare the native builder fix; no credentials or runtime files were changed.

Existing exploratory object M-BCT-AA4M was created earlier through the native GUI using an older template. It is retained and is not part of the all-new cohort.

Next: load the pack through an authorized supported path; create its cohort; add the cross-object lineage relationships using owning controls; publish returned EUIDs in the document. Document editing can continue independently.

# Pack semantics

Material containers directly hold material portions: tube, well, bottle. Organizing containers hold other containers: a plate has fixed wells; a rack has movable occupants; a holding rack, box, or freezer may have no assigned positions. Layout and mobility are independent dimensions.

A material portion is localized to one owning material container. A transfer into another holder creates a new destination portion even when all material is moved. Whole-holder relocation preserves the portion identity. A pool has multiple material parents and one holder. Corrections retain superseded evidence; unplaced registrations may remain unbound.

The pack includes five portion kinds, empty material containers, organizing containers, filled synthetic fixtures, full 96-well plate geometries, and one cohort workset. A selected well always has its own EUID and explicit row/column address. Every selected filled fixture creates its own material portion. Fixture quantities are deliberately not invented.

The cohort contains empty/basic objects; eight blood tubes; three saliva tubes; source and aliquot buccal tubes; half-column, half-quantity, and remap pools; racks and nested storage; eight plates for source column, three destination rows, unchanged-address stamp, explicit remap, saliva aliquots, and saliva extraction. The workset `member_of` edges group the demonstration only; they are not physical containment.

Creation layouts establish `contains` and `HOLDS_MATERIAL` edges. Source-to-output `DERIVED_FROM` and container-to-container operation provenance must be added explicitly after instantiation. No copied EUID metadata substitutes for lineage. No EUID in this pack is fabricated.

All specimens and events are synthetic documentation examples. Metadata such as `fixed_to_parent`, `container_kind`, geometry, and `identity_scope` describes intended behavior. `UNIVERSAL_PASS@1` does not enforce the proposed invariants; do not claim these are implemented constraints or completed physical operations.

# Loading

Use Bloom's supported seed command in a deployment containing this pack when its owning loader is functional. For the already approved TapDB CLI path, supply the explicit existing operator-capable target and the directory containing this pack, with `db data seed --include-workflow --skip-existing`. Do not overwrite existing definitions, invent operator settings, or substitute runtime credentials for the operator. The CLI's own preflight is authoritative.

# Gate 0 and execution

| Item | State | Evidence |
| --- | --- | --- |
| Scope and names | Complete | User request and naming correction |
| Pack authored | Complete | 26 new template definitions |
| Native form validation | Accepted | Existing builder returned no issues |
| Native save | Failed | Transaction isolation error; rollback |
| Approved CLI load | Blocked | Operator preflight; no operator configured |
| Source commit | Included in this commit | This pack and this ledger only |
| Live cohort and cross-edges | Pending | No new cohort EUID yet |
| Native document update | In progress | Existing Google Doc |
