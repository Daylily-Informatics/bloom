# Stage-To-Delete Manifest

This directory quarantines files moved out of active paths because they are currently unreachable/unreferenced by route/import/template/reference scans.

| Moved At (UTC) | Original Path | Quarantine Path | Reason | Evidence Query |
|---|---|---|---|---|
| 2026-03-03T14:51:08Z | templates/legacy/admin.html | stage_to_delete/templates/legacy/admin.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/assay.html | stage_to_delete/templates/legacy/assay.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/audit_log_by_user.html | stage_to_delete/templates/legacy/audit_log_by_user.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/base.html | stage_to_delete/templates/legacy/base.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/database_statistics.html | stage_to_delete/templates/legacy/database_statistics.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/dindex2.html | stage_to_delete/templates/legacy/dindex2.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/equipment_overview.html | stage_to_delete/templates/legacy/equipment_overview.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/euid_details.html | stage_to_delete/templates/legacy/euid_details.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/index.html | stage_to_delete/templates/legacy/index.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/json_editor.html | stage_to_delete/templates/legacy/json_editor.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/object_templates_summary.html | stage_to_delete/templates/legacy/object_templates_summary.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/plate_carosel.html | stage_to_delete/templates/legacy/plate_carosel.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/plate_carosel2.html | stage_to_delete/templates/legacy/plate_carosel2.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/plate_display.html | stage_to_delete/templates/legacy/plate_display.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/queue_details.html | stage_to_delete/templates/legacy/queue_details.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/reagent_overview.html | stage_to_delete/templates/legacy/reagent_overview.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/user_home.html | stage_to_delete/templates/legacy/user_home.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/workflow_details.html | stage_to_delete/templates/legacy/workflow_details.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | templates/legacy/workflow_summary.html | stage_to_delete/templates/legacy/workflow_summary.html | legacy-unreachable |  |
| main.py get_template() entrypoint + Jinja dependency closure scan |  |  |  |  |
| 2026-03-03T14:51:08Z | static/legacy/skins/fdx_a.css | stage_to_delete/static/legacy/skins/fdx_a.css | deprecated-unreferenced |  |
| rg reference scan outside static/legacy |  |  |  |  |
| 2026-03-03T14:51:08Z | static/legacy/skins/vlight.css | stage_to_delete/static/legacy/skins/vlight.css | deprecated-unreferenced |  |
| rg reference scan outside static/legacy |  |  |  |  |
| 2026-03-03T14:51:08Z | static/legacy/skins/json_editor.css | stage_to_delete/static/legacy/skins/json_editor.css | deprecated-unreferenced |  |
| rg reference scan outside static/legacy |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/config.js | stage_to_delete/static/js/dag-explorer/config.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/graph.js | stage_to_delete/static/js/dag-explorer/graph.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/filters.js | stage_to_delete/static/js/dag-explorer/filters.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/events.js | stage_to_delete/static/js/dag-explorer/events.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/search.js | stage_to_delete/static/js/dag-explorer/search.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | static/js/dag-explorer/index.js | stage_to_delete/static/js/dag-explorer/index.js | unused-unreferenced |  |
| only referenced by quarantined legacy/dindex2.html |  |  |  |  |
| 2026-03-03T14:51:08Z | bloom_lims/bin/create_erd_graphviz_from_sqlalchemy_orm.py | stage_to_delete/bloom_lims/bin/create_erd_graphviz_from_sqlalchemy_orm.py | unused-unreferenced |  |
| python import/reference heuristic scan |  |  |  |  |
| 2026-03-03T14:51:08Z | bloom_lims/bin/print_audit.py | stage_to_delete/bloom_lims/bin/print_audit.py | unused-unreferenced |  |
| python import/reference heuristic scan |  |  |  |  |
| 2026-03-03T14:51:08Z | bloom_lims/bin/print_audit_children.py | stage_to_delete/bloom_lims/bin/print_audit_children.py | unused-unreferenced |  |
| python import/reference heuristic scan |  |  |  |  |
