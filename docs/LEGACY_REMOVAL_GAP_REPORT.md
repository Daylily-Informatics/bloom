# Bloom Legacy Removal Gap Report

This report tracks legacy GUI surfaces removed during the `legacy.py` retirement pass and whether a modern replacement exists.

## Migrated to non-legacy modules

- `legacy.py` route module moved to `/bloom_lims/gui/routes/operations.py`.
- EUID detail and workflow action buttons now call `POST /ui/actions/execute` and execute through TapDB-pattern dispatcher semantics.
- Modern action JS moved to `/static/modern/js/action_buttons.js`.

## Retired (no modern product pattern in current beta scope)

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

## Behavior changes for legacy utility pages

- `/index2` and `/lims` now redirect to `/`.
- `/query_by_euids` still exists, but renders a simple modern-safe HTML table (no legacy templates/assets).
- `/file_set_urls` returns JSON instead of rendering a legacy template.

## Rationale

- The retired pages were coupled to `templates/legacy/*` and `static/legacy/*` and had no supported modern UI ownership path.
- Beta-critical GUI and API flows are preserved; non-critical legacy pages were removed instead of carrying compatibility shims.
