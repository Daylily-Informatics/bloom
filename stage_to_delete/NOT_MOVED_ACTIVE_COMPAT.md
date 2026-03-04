# Not Moved: Active Compatibility/Deprecated Runtime Code

This file documents active compatibility/deprecated code paths intentionally **not** moved in the safe quarantine pass.

## Why not moved
These files/routes are still referenced by active runtime paths (routes, templates, auth/session flows, or API clients) and require an explicit hard-cut migration plan.

## Active compatibility/deprecated surfaces retained

### Legacy template runtime still in use
- `main.py` routes that still render legacy templates directly:
  - `legacy/index2.html`
  - `legacy/lims_main.html`
  - `legacy/search_results.html`
  - `legacy/search_error.html`
  - `legacy/control_overview.html`
  - `legacy/vertical_exp.html`
  - `legacy/bloom_schema_report.html`
  - `legacy/bulk_create_files.html`
  - `legacy/create_file_report.html`
  - `legacy/dewey.html`
  - `legacy/trigger_downloads.html`
  - `legacy/download_error.html`
  - `legacy/file_set_search_results.html`
  - `legacy/visual_report.html`
  - `legacy/create_instance_form.html`
  - `legacy/file_set_urls.html`
  - `legacy/admin_template.html`

### Active legacy assets
- `static/legacy/action_buttons.js` is still loaded by modern templates:
  - `templates/modern/euid_details.html`
  - `templates/modern/workflow_details.html`
- `static/legacy/skins/bloom.css` remains referenced for user skin/default style paths.

### Active deprecated endpoints retained for compatibility window
- In `main.py`:
  - `/delete_object`
  - `/get_dagv2`
  - `/add_new_edge`
  - `/delete_node`
  - `/delete_edge`
- These are currently marked deprecated but still present intentionally.

### Active auth/API compatibility code
- Legacy API key compatibility path and role fallback logic:
  - `bloom_lims/api/v1/dependencies.py`
  - `bloom_lims/auth/services/groups.py`
  - `bloom_lims/auth/rbac.py`
- Legacy search v1 API compatibility shim:
  - `bloom_lims/api/v1/search.py`

### Active domain compatibility shims/fallback behavior
- Legacy alias/fallback logic in domain/core modules remains:
  - `bloom_lims/domain/base.py`
  - `bloom_lims/domain/workflows.py`
  - `bloom_lims/domain/files.py`
  - `bloom_lims/domain/utils.py`

## Hard-cut follow-up required
A separate hard-cut phase is needed to remove these safely, including route/API migration, template replacement, and compatibility contract updates.
