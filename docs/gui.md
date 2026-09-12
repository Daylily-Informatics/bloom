# Bloom GUI

Bloom's GUI is the browser-facing operations surface for the service. It is where an authenticated operator inspects queue runtime, navigates material state, searches across the material graph, uses the graph explorer, and accesses admin-only observability and token-management pages. It is not a second application bolted on top of the API; it is part of the same FastAPI process and shares the same config, session, and RBAC vocabulary.

Bloom now uses the `daylily-auth-cognito==2.1.5` browser/session boundary. Browser sessions stay token-free, callback exchange is async in the web path, and runtime code should not depend on `daylily_auth_cognito.cli`.

## Session And Login Model

The GUI auth flow is Cognito Hosted UI based and implemented through `daylily-auth-cognito` session helpers.

Current route family:

- `/login`
- `/auth/login`
- `/auth/callback`
- `/auth/logout`
- `/logout`
- `/auth/error`

Current behavior from `bloom_lims/gui/web_session.py` and `bloom_lims/gui/deps.py`:

- session middleware is installed during app startup
- the session cookie name is `bloom_session`
- session max age is derived from `auth.session_timeout_minutes`
- Bloom stores a normalized session principal and `user_data`, not raw OAuth tokens
- callback and logout URLs come from Bloom config, not from ad hoc request reconstruction

That last point matters behind reverse proxies: Bloom is designed to trust its YAML auth config for callback/logout URLs instead of deriving them from the internal bind address.

## Supported Local-Dev Position

The supported GUI bring-up path is:

1. configure Cognito in the deployment-scoped Bloom YAML
2. configure the TapDB namespace config Bloom delegates to
3. start Bloom normally with `bloom server start`

The codebase still contains test/dev bypass paths such as `BLOOM_OAUTH=no` and `BLOOM_DEV_AUTH_BYPASS`, but those are not the supported normal runtime model. The committed E2E tests use auth test fixtures and bypass-friendly paths where needed; operators should not treat those flags as standard configuration.

## Main Screen Families

| Screen | Route | What it is for |
| --- | --- | --- |
| Dashboard | `/` | top-level operator landing page |
| Search | `/search` | unified search across instance, template, lineage, and audit records |
| Create object wizard | `/create_object` | create instances from the modern creation flow |
| Queue runtime | `/queue_details` | inspect current queue/runtime objects |
| Equipment overview | `/equipment` -> `/equipment_overview` | equipment inventory and navigation |
| Reagent overview | `/reagents` -> `/reagent_overview` | reagent inventory and navigation |
| Template-driven create | `/create_from_template` | create an object directly from a chosen template |
| User home | `/user_home` | operator home and admin affordances |
| Admin | `/admin` | preference management, token issuance, dependency/admin links |
| Admin metrics | `/admin/metrics` | raw DB metrics view |
| Admin observability | `/admin/observability` | observability rollups |
| Admin anomalies | `/admin/anomalies` | anomaly listing and detail pages |
| Bloom graph explorer | `/dindex2` | Bloom-specific Cytoscape graph browser |
| Embedded TapDB GUI | `/tapdb` (default) | Native object/template/lineage/audit views through host-session auth |
| Embedded TapDB graph | `/tapdb/graph` (default mount) | Native TapDB graph UI |

The dashboard is the best summary of current product emphasis. Its cards and links point toward queue runtime, search, equipment, reagents, and admin, which matches the queue-centric beta posture documented elsewhere in the repo.

## Notable Route Behavior

Some GUI route choices are worth calling out because they reveal current product intent:

- `/index2` and `/lims` still exist, but they redirect back to the dashboard path rather than defining a separate product surface.
- `/controls` is retired and returns `404`.
- `/graph` is retired as an alias; the supported graph explorer path is `/dindex2`.
- workflow/workset pages are not current supported product surfaces even though some workflow-related code still exists in-repo.

## Roles And Permissions

The GUI uses Bloom's current role ladder:

| Role | Practical GUI effect |
| --- | --- |
| `READ_ONLY` | inspect records and non-mutating surfaces |
| `READ_WRITE` | perform normal record mutations and queue/runtime actions |
| `ADMIN` | access Bloom admin pages and admin-only graph mutations; maps to admin in the TapDB host bridge |

Current role permissions:

- `READ_ONLY`: `bloom:read`, `token:self_manage`
- `READ_WRITE`: `bloom:read`, `bloom:write`, `token:self_manage`
- `ADMIN`: full permission set, including admin token management

### Groups

Groups are separate from roles. They do not currently form a second role ladder in the router layer. Instead they act as feature and scope markers.

Current named system groups include:

- `API_ACCESS`
- `ENABLE_ATLAS_API`
- `ENABLE_URSA_API`
- `bloom-rnd`
- `bloom-clinical`
- `bloom-auditor`

Codes such as `bloom-readonly`, `bloom-readwrite`, and `bloom-admin` are defined in the RBAC module, but the current request path primarily derives permissions from roles and uses groups for feature gating and cohort tagging.

## Admin-Only GUI Behavior

Two important admin-only browser surfaces exist today.

### Admin Pages

`/admin`, `/admin/metrics`, `/admin/observability`, and `/admin/anomalies` are guarded by an admin session check. Non-admin users are redirected to:

```text
/user_home?admin_required=1
```

The admin page currently includes:

- preference management
- API token administration and issuance
- links to observability and anomaly views
- dependency info, including Zebra Day admin links when configured

### Embedded TapDB GUI

The default mount is `/tapdb`, configured by `BLOOM_TAPDB_MOUNT_PATH`; `BLOOM_TAPDB_MOUNT_ENABLED=0` disables it. When enabled, a mount failure aborts startup. The implementation uses public `create_tapdb_gui_app` and `TapdbHostBridge` with an explicit TapDB config.

The bridge resolves the existing Bloom session and maps ADMIN to TapDB admin; other authenticated Bloom users map to TapDB user. READ_ONLY and READ_WRITE are therefore not separate native GUI roles. TapDB handles its route permissions. The entire mount is not guarded by the old Bloom-admin-only redirect wrapper.

Native object details are at `/tapdb/object/{euid}` and the native graph is at `/tapdb/graph` with the default mount. Use persisted identifiers only. Native graph consumers such as Kahlo use `/api/dag/v2/*`, separately from the Bloom graph explorer described below.

## Graph Explorer

The graph explorer is one of the most distinct parts of Bloom's GUI.

Current path:

```text
/dindex2
```

Current supporting helper APIs:

- `/api/graph/data`
- `/api/object/{euid}`
- `/api/graph/external`
- `/api/graph/external/object`
- `/api/lineage`
- `DELETE /api/object/{euid}`

Current user-facing characteristics from templates and tests:

- Cytoscape-based graph rendering
- search/highlight inside the loaded graph
- external graph expansion for Atlas-backed references
- admin-only mutation gestures
- restored legacy graph interaction shortcuts in the modern graph client

Examples of graph-only affordances surfaced in `templates/modern/dag_explorer.html`:

- `D + right click`: delete node or edge, admin only
- `L + left click`: lineage creation gesture, admin only
- external reference expansion when a node exposes graph-expandable Atlas links

This is a strong example of Bloom's "operator tool" posture. The graph explorer is not just a read-only visualization; it is a material-state debugging and maintenance surface.

## Search UI

The GUI search page at `/search` is the browser face of search v2. It supports:

- free-text query
- category filters
- record-type filters
- facet display
- pagination
- export through `/api/v1/search/v2/export`

It also accepts form submissions translated from older Dewey-oriented search forms. In other words, the GUI is already part of the migration path away from older search assumptions.

## Queue Runtime, Equipment, Reagents, And Create Flows

These are the operator-facing screens most people will use day to day.

### Queue Runtime

`/queue_details` exposes recent queue/runtime objects and gives the operator a focused view into the current queue-centric beta state.

### Equipment And Reagents

`/equipment_overview` and `/reagent_overview` render inventory-style summaries from current instance/template data. They are part of what makes Bloom a practical operator tool instead of only an API service.

### Create Flows

Bloom currently exposes two creation entrypoints:

- `/create_object`: the more guided wizard
- `/create_from_template`: a direct template-driven path

Older workflow/workset-centric creation surfaces are not the current product direction.

### Lab Actions

`/lab-actions` exposes the temporary wet-lab action wizard for:

- incoming tube to extraction plate mapping
- extraction plate to extraction QC plate mapping
- extraction plate to sequencing-library plate mapping
- sequencing-library pool tube creation
- sequencing run set setup
- generic lab/run set creation and member management
- plate-well associated data attachment
- spreadsheet upload for `.csv` and `.xlsx` lab-action sheets
- plate CSV export
- ILMN sample-sheet download
- generic EUID barcode print dispatch

The GUI is backed by `/api/v1/lab-actions/*`. The GUI should remain an operator-friendly wrapper over the API rather than a separate behavior surface.

The detailed runbook is [`lab_actions.md`](lab_actions.md). It includes the exact template matrix, lineage vocabulary, API examples, and production rollout checklist.

## Evidence and release boundaries

The [completed migration ledger](plans/20260911T150553Z_bloom_tapdb_10_1_migration_ledger.md) records normal SSO/dashboard access on Bloom 10.0.1 and native graph display through Kahlo 8.0.1. The dashboard median improved from 910.05 ms to 282.65 ms in the recorded single-round comparison; stats improved by 1.994x. These are measurements tied to that migration, not fresh claims for every route or deployment.

The [phase-2 backlog](plans/20260912T045329Z_bloom_phase_2_backlog.md) includes stale footer branch/tag/commit text and long-lived request sessions. Use immutable release/image receipts for deployment provenance.

For current GUI behavior, consult routes under `bloom_lims/gui/routes`, templates under `templates/modern`, the public TapDB bridge and the native DAG integration. Existing GUI/browser tests are reference material. Do not run them, collect a new screenshot campaign or redeploy for a docs-only release; follow [AGENTS.md](../AGENTS.md).

## Practical Caveats

The two most common GUI integration mistakes are configuration mistakes, not code mistakes:

- incorrect Cognito callback/logout URLs
- attempting to run with missing Bloom YAML auth values and then falling back to dev bypass flags

If the GUI behaves strangely, verify the deployment-scoped Bloom YAML and TapDB config first. The GUI depends on the same config truth as the rest of the service.
