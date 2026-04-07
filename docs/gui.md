# Bloom GUI

Bloom's GUI is the browser-facing operations surface for the service. It is where an authenticated operator inspects queue runtime, navigates material state, searches across the material graph, uses the graph explorer, and accesses admin-only observability and token-management pages. It is not a second application bolted on top of the API; it is part of the same FastAPI process and shares the same config, session, and RBAC vocabulary.

Bloom now uses the `daylily-auth-cognito` 2.0 browser/session boundary. Browser sessions stay token-free, callback exchange is async in the web path, and runtime code should not depend on `daylily_auth_cognito.cli`.

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
| Graph explorer | `/dindex2` | Cytoscape graph browser |

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
| `ADMIN` | access admin pages, mounted TapDB admin, and admin-only graph mutations |

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

### Mounted TapDB Admin

TapDB admin is embedded under:

```text
/admin/tapdb
```

The mount is guarded before the request reaches TapDB:

- unauthenticated browser requests redirect to `/login`
- unauthenticated JSON/XHR gets `401`
- non-admin browser requests redirect to `/user_home?admin_required=1`
- non-admin JSON/XHR gets `403`

This is a useful operational boundary: mounted TapDB admin is explicitly a Bloom-admin browser surface.

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

## Playwright Coverage

Current committed browser E2E coverage is deliberately narrow.

Authoritative files:

- [../tests/e2e/README.md](../tests/e2e/README.md)
- [../tests/e2e/test_auth_e2e.py](../tests/e2e/test_auth_e2e.py)

Current coverage highlights:

- login round trip through the browser
- logout round trip
- protected-route redirect after logout

Current limitations:

- no committed end-to-end coverage yet for dashboard actions, queue runtime, equipment, search, graph, or admin pages
- no checked-in rich Playwright HTML report bundle or curated screenshot gallery

So when you need to understand the GUI today, the real source hierarchy is:

1. route code under `bloom_lims/gui/routes`
2. templates under `templates/modern`
3. GUI-focused tests
4. then historical docs for context

## Practical Caveats

The two most common GUI integration mistakes are configuration mistakes, not code mistakes:

- incorrect Cognito callback/logout URLs
- attempting to run with missing Bloom YAML auth values and then falling back to dev bypass flags

If the GUI behaves strangely, verify the deployment-scoped Bloom YAML and TapDB config first. The GUI depends on the same config truth as the rest of the service.
