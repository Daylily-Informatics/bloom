# Bloom Legacy Removal Gap Report

This report tracks retired Bloom product surfaces and the modern ownership path that replaces them for the queue-centric beta system.

## Active modern ownership

- Legacy utility routes from `legacy.py` are owned by `/bloom_lims/gui/routes/operations.py`.
- UI action execution is owned by `POST /ui/actions/execute` in `/bloom_lims/gui/routes/operations.py`.
- Modern action UI behavior is implemented by `/static/modern/js/action_buttons.js` and `/bloom_lims/gui/actions.py`.

## Retired product surfaces

### Workflow/workset retirement

- `/api/v1/workflows/*` is not mounted.
- `/api/v1/worksets/*` is not mounted.
- Workflow GUI router mount is removed from `/bloom_lims/gui/router.py`.
- `/workflows` is hard-disabled with a retirement response.

### Retired utility pages (no beta product replacement)

- `/controls`
- `/control_overview`
- `/vertical_exp`
- `/plate_carosel2`
- `/get_related_plates`
- `/bloom_schema_report`
- `/bulk_create_files`
- `/visual_report`
- `/create_instance/{template_euid}`
- `/admin_template` (GET/POST)

## Compatibility behavior retained

- `/index2` and `/lims` now redirect to `/`.
- `/query_by_euids` still exists and renders a modern-safe HTML table (no legacy templates/assets).
- `/file_set_urls` returns JSON instead of rendering a legacy template.

## Rationale and isolation

- Queue-based operations are the only supported Bloom work-management model for beta.
- Workflow/workset code may remain on disk for archival context, but it is isolated from mounted API/GUI product surfaces.
- Non-critical legacy pages coupled to `templates/legacy/*` and `static/legacy/*` were retired instead of preserved via compatibility shims.
