# Bloom Queue Refactor Execution Plan (Finalization Pass)

## Scope

This document tracks the final Bloom beta-completion pass for:

- hard retirement of workflow/workset/test-requisition API+GUI surfaces
- create-page exposure/sorting fixes for non-retired templates
- modern TapDB action execution parity and reliability
- admin token/group UX fixes
- Atlas/Ursa external integration authorization gates
- zebra service start reliability

## Change Groups

1. **Legacy retirement and routing**
   - unmount `/api/v1/workflows` and `/api/v1/worksets`
   - remove workflow GUI router mounts and nav/dashboard links
   - keep workflow artifacts on disk only as non-mounted retired code

2. **Create flow correctness**
   - remove workflow/assay shortcut behavior
   - filter retired categories at API source: `workflow`, `workflow_step`, `test_requisition`
   - sort category/type/subtype/version options case-insensitively with stable ordering

3. **Action execution parity**
   - keep `/ui/actions/execute` as active endpoint independent of workflow module
   - propagate dispatcher status and fail on dispatcher `error/failed` outcomes
   - robust action-key lookup and action-template UID backfill for legacy instances
   - inject required UI fields for core actions (`set_object_status`, `add_relationships`)

4. **Admin + RBAC integration**
   - add system groups: `ENABLE_ATLAS_API`, `ENABLE_URSA_API`
   - add admin issue-token-for-selected-user endpoint
   - make add-user deterministic (`added`, `exists`, `reactivated`)
   - add Atlas/Ursa enablement panels in admin GUI
   - enforce Atlas/Ursa groups on external API routes

5. **zebra_day service integration**
   - consume shared printer and label-profile state through the zebra_day API
   - stop Bloom-owned process management for zebra_day
   - submit print jobs through zebra_day instead of direct local printer access

## Beta Acceptance Checks

- Atlas external routes are token-authenticated, write-permitted, and `ENABLE_ATLAS_API` gated.
- Resolver route remains full-key (`run_euid + flowcell_id + lane + library_barcode`) and `ENABLE_URSA_API` gated.
- Create page does not offer retired object domains.
- Action buttons execute through modern TapDB path with truthful success/error reporting.
- Admin page can:
  - add API users with deterministic feedback
  - issue a token for a selected API user
  - enable Atlas/Ursa API group access
- Bloom admin links to zebra_day but does not start or manage the process.

## Breaking Changes

- `/api/v1/workflows/*` and `/api/v1/worksets/*` are retired (no active beta support).
- GUI workflow pages are retired and no longer linked from navigation/dashboard.
- External integration routes now require explicit Atlas/Ursa enablement groups in addition to token auth and permissions.
