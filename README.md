# BLOOM

## Overview

Bloom is the LSMC internal material and container graph service. It owns laboratory containers, materials/content, equipment, lineage, recursive template creation, search, and graph views. Atlas owns orders and customer-facing accession context; Bloom owns the physical/material execution graph.

Current Dayhoff pin: `7.0.14`. Current TapDB dependency: `daylily-tapdb @ ...@9.0.4`.

Bloom is internal-only in Dayhoff exposure policy. It must be reachable only through approved LSMC networks and Dayhoff-generated service credentials.

## Quickstart

```bash
cd /Users/jmajor/projects/mega_dayhoff/repos_work/bloom
source ./activate <deploy-name>
bloom --help
bloom config init --help
bloom db build --target local
bloom server start --port 8912
```

Runtime config, service config, TapDB config, and registry paths must be passed explicitly. Do not rely on deployment-name guessing or `~/.config` fallback discovery.

## CLI Interface

The primary CLI is `bloom`. It covers config initialization, DB/bootstrap tasks, service startup, object/template workflows, and operational helpers.

Bloom can delegate low-level storage lifecycle to `tapdb` and shared Cognito lifecycle to `daycog` only where the Bloom CLI or docs explicitly say so.

Common command families:

| Family | Purpose |
|---|---|
| `bloom config ...` | Materialize explicit deployment-scoped service config. |
| `bloom db ...` | Build or verify Bloom-owned local database state through supported paths. |
| `bloom server ...` | Start the FastAPI service with explicit generated config. |
| `bloom objects/templates/lineage ...` | Work with Bloom-owned containers, materials, templates, and lineages where exposed by the CLI. |
| `bloom tokens/admin ...` | Manage supported internal/admin auth surfaces without printing secrets. |

For normal user/admin behavior, the CLI, API, and GUI are alternate surfaces over the same Bloom object, template, lineage, and auth capabilities. A feature should not be CLI-only, API-only, or GUI-only unless the docs say why.

## GUI

Bloom exposes a FastAPI/Jinja GUI for internal operators. Current surfaces include dashboard/home, object search and details, container/content/equipment operations, graph views, auth/profile flows, the `/lab-actions` wet-lab action wizard, and the mounted TapDB GUI at `/tapdb` when configured by Dayhoff.

`/lab-actions` is the temporary operator flow for mapping incoming biospecimen tubes to extraction plates, sequencing-library plates, pool tubes, and sequencing run sets. It is backed by `/api/v1/lab-actions/*`; GUI actions should not have behavior that is unavailable through the API.

See [`docs/lab_actions.md`](docs/lab_actions.md) for the template matrix, lineage contract, API examples, GUI flow, and production rollout checklist for this surface.

Every human-visible EUID should link to the canonical TapDB object page at `/tapdb/object/{euid}` unless Bloom owns a more specific detail page; service-specific pages should still link back to canonical TapDB details.

## API

The primary API is under `/api/v1/*`. Current route families include objects, containers, content, equipment, execution queue, batch operations, templates, subjects, lineages, stats, search, object creation, lab actions, user tokens, admin auth, external specimens, Atlas integration, beta lab integration, and graph APIs.

The lab-action route family includes:

- `POST /api/v1/lab-actions/extraction-plates`
- `POST /api/v1/lab-actions/seq-library-plates`
- `POST /api/v1/lab-actions/seq-library-pools`
- `POST /api/v1/lab-actions/seq-runs`
- `GET /api/v1/lab-actions/seq-runs/{set_euid}/samplesheet`
- `GET /api/v1/lab-actions/plates/{plate_euid}/mapping.csv`
- `POST /api/v1/lab-actions/print-euids`

The generic run-set template is `set/run-set/generic/1.01`. It is used for sequencing-run sets and other temporary Bloom-owned sets of internal or external EUIDs.

Health and observability routes include `/healthz`, `/readyz`, `/health`, `/obs_services`, `/api_health`, `/endpoint_health`, `/db_health`, `/my_health`, and `/auth_health` when configured for Dayhoff observability.

## Testing Info

Focused checks:

```bash
python -m pytest tests -q
python -m pytest tests/test_lsmc_ui_skin_system_contract.py -q
```

Deployed browser evidence should target `https://bloom.<deploy>.dev.lsmc.bio` and include the dashboard, object search/detail, TapDB mount, graph, and auth redirect surfaces. Current committed `jemdev5` evidence is linked from Dayhoff `docs/releases/dayhoff_7_0_61_jemdev5_evidence/`.

## Technical Details, History, And Linkouts

- [`docs/apis.md`](docs/apis.md): API details.
- [`docs/gui.md`](docs/gui.md): GUI routes and screenshots when current.
- [`docs/lab_actions.md`](docs/lab_actions.md): extraction/library/pooling/sequencing-run action flow, template matrix, and production rollout checklist.
- [`docs/architecture.md`](docs/architecture.md): domain model and runtime boundaries.
- [`docs/becoming_a_discoverable_service.md`](docs/becoming_a_discoverable_service.md): Dayhoff/Kahlo observability contract.
- [`docs/plans/`](docs/plans/): active ledgers.
- [`docs/old_docs/`](docs/old_docs/): historical material only.

Current Bloom language should use Container and Material separation. Order, OrderTest, SubjectRef, AccessionCase, and fulfillment semantics are Atlas-owned or cross-service references, not Bloom-owned order lifecycle objects.
