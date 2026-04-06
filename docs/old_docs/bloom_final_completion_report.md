# Bloom Final Completion Report

Date: March 8, 2026

## Completion statement

Bloom is now queue-centric on supported product surfaces.

- API and GUI workflow/workset management surfaces are retired from mounted routes.
- Queue-based operations are the supported Bloom work-management model for beta.
- Modern TapDB action execution remains active via `/ui/actions/execute` and no longer depends on workflow route ownership.

## What was removed

- API mount for `/api/v1/workflows/*`.
- API mount for `/api/v1/worksets/*`.
- GUI workflow router mount from `/bloom_lims/gui/router.py`.
- Workflow navigation/dashboard links and workflow shortcut UI elements from modern templates.
- Create-flow exposure of retired categories/types (`workflow`, `workflow_step`, `test_requisition`).

## What was isolated

- Workflow/workset compatibility module names remain importable, but runtime behavior is retired and not mounted as supported API/GUI product paths.
- `/workflows` UI path is hard-disabled with retirement behavior.

## Relationship and action anti-pattern fixes in this pass

- Action execution status propagation now surfaces dispatcher failures as errors instead of forced success.
- Modern action key/template resolution now backfills missing template linkage for resolvable instances to avoid `ActionError Not Found` on valid actions.
- Required action inputs are enforced in UI/API execution paths for status updates and relationship creation actions.
- Atlas/Ursa external integration routes are group-gated (`ENABLE_ATLAS_API`, `ENABLE_URSA_API`) in addition to token auth and permissions.

## Admin and operations fixes in this pass

- "Add API user" now returns deterministic membership outcomes (`added`, `exists`, `reactivated`) and persists membership.
- Admin-issued token endpoint for selected users is implemented (`POST /api/v1/admin/user-tokens/issue`).
- Admin UI now exposes Atlas/Ursa API enablement controls and selected-user token issuance UX.
- Zebra start path now uses non-blocking service start with deterministic `already running` / `started` / `failed` responses and command fallback logic.

## Create flow behavior in this pass

- Non-retired, non-disabled/internal templates are exposed in create APIs.
- Category/type/subtype/version options are sorted case-insensitively with deterministic tie-breaking.
- Retired workflow/test-requisition shortcuts and icon mappings are removed.

## Queue-based status

Bloom is fully queue-based on supported product API/GUI surfaces for beta.

## Non-blocking archival workflow code

Yes. Archival workflow/workset code remains in-repo but is isolated from mounted product surfaces.

## Commands and tests run

Executed exactly as requested:

- `source ./activate <deploy-name> >/dev/null 2>&1 && pytest tests/test_api_v1.py tests/test_gui_endpoints.py`
  - Functional result: `338 passed, 28 skipped`
  - Exit code non-zero due coverage gate (`fail_under=39`, total `30.96%`).
- `source ./activate <deploy-name> >/dev/null 2>&1 && pytest tests/test_action_execution.py`
  - Functional result: `2 passed`
  - Exit code non-zero due coverage gate (`7.99%`).
- `source ./activate <deploy-name> >/dev/null 2>&1 && pytest tests/test_admin_auth.py tests/test_user_api_tokens.py`
  - Functional result: `4 passed`
  - Exit code non-zero due coverage gate (`23.19%`).
- `source ./activate <deploy-name> >/dev/null 2>&1 && pytest tests/test_external_specimens.py tests/test_beta_lab.py`
  - Functional result: `5 passed`
  - Exit code non-zero due coverage gate (`20.93%`).
- `source ./activate <deploy-name> >/dev/null 2>&1 && pytest tests/test_operations_routes.py -k zebra`
  - Functional result: `2 passed, 2 deselected`
  - Exit code non-zero due coverage gate (`20.68%`).

Additional check run:

- `source ./activate <deploy-name> >/dev/null 2>&1 && ruff check bloom_lims tests`
  - Non-green due large pre-existing repo baseline violations.
