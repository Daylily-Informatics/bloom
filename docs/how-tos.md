# Bloom How-Tos

This file is the practical companion to the higher-level docs. Every command here is intended to be copy-pastable and aligned with Bloom's current CLI surface.

Bloom's shared Cognito workflow now comes from `daycog` plus `daylily-auth-cognito` 2.0. Use the browser/session and runtime helper split from that package, and keep service runtime code out of `daylily_auth_cognito.cli`.

## First-Run Local Setup

From the repo root:

```bash
source ./activate <deploy-name>
bloom --help
bloom config path
```

For a typical local bring-up:

```bash
source ./activate bringup
bloom config init
bloom db build --target local
bloom config status
bloom config doctor
```

What those steps do:

- `source ./activate <deploy-name>` creates or activates the deployment-scoped repo environment
- `bloom config init` seeds the deployment-scoped YAML from the packaged template
- `bloom db build --target local` delegates runtime/bootstrap work to TapDB
- `bloom config status` shows the effective current config
- `bloom config doctor` validates environment, dependencies, config, and writable paths

Bloom's supported config paths are deployment-scoped:

```text
~/.config/bloom-<deploy-name>/bloom-config-<deploy-name>.yaml
~/.config/tapdb/bloom/bloom-<deploy-name>/tapdb-config.yaml
```

## Inspect Config And Runtime State

Show where Bloom expects its config:

```bash
source ./activate bringup
bloom config path
```

Inspect the resolved config status:

```bash
source ./activate bringup
bloom config status
```

Run a full doctor pass:

```bash
source ./activate bringup
bloom config doctor
```

Edit the Bloom YAML in your configured editor:

```bash
source ./activate bringup
bloom config edit
```

## Build The Local Runtime

The current supported bootstrap command is:

```bash
source ./activate bringup
bloom db build --target local
```

Seed template data when needed:

```bash
source ./activate bringup
bloom db seed
```

If you see older references to `bloom db init` in historical notes, activation banners, or external service-catalog metadata, use `bloom db build --target local`. The current Bloom CLI help is authoritative.

## Run The Server

Start:

```bash
source ./activate bringup
bloom server start --port 8912
```

Check liveness and readiness:

```bash
curl -k https://127.0.0.1:8912/healthz
curl -k https://127.0.0.1:8912/readyz
```

Inspect logs and status:

```bash
source ./activate bringup
bloom server status
bloom server logs
```

Stop:

```bash
source ./activate bringup
bloom server stop
```

## Configure Cognito The Supported Way

Bloom's normal auth setup is YAML-first for service startup, with shared Cognito lifecycle delegated through `daycog` and namespaced binding delegated through `tapdb`.

### 1. Inspect available shared Cognito state

```bash
source ./activate bringup
daycog list-pools --region us-west-2
daycog list-apps --pool-name <shared-pool-name>
```

### 2. Create or inspect the Bloom app client through the delegated path

If the shared pool already has a `bloom` app client, reuse it. If not:

```bash
source ./activate bringup
tapdb --config ~/.config/tapdb/bloom/bloom-bringup/tapdb-config.yaml --env dev \
  cognito add-app dev \
  --app-name bloom \
  --pool-name <shared-pool-name> \
  --callback-url https://localhost:8912/auth/callback \
  --logout-url https://localhost:8912/
```

### 3. Bind the TapDB namespace to the shared Cognito values

```bash
source ./activate bringup
tapdb --config ~/.config/tapdb/bloom/bloom-bringup/tapdb-config.yaml --env dev \
  db-config update \
  --env dev \
  --cognito-user-pool-id <pool-id> \
  --cognito-app-client-id <client-id> \
  --cognito-client-name bloom \
  --cognito-region us-west-2 \
  --cognito-domain <hosted-ui-domain> \
  --cognito-callback-url https://localhost:8912/auth/callback \
  --cognito-logout-url https://localhost:8912/
```

### 4. Put the same values in Bloom's YAML

Open the Bloom config:

```bash
source ./activate bringup
bloom config edit
```

Set the auth block:

```yaml
auth:
  cognito_user_pool_id: <pool-id>
  cognito_client_id: <client-id>
  cognito_region: us-west-2
  cognito_domain: <hosted-ui-domain>
  cognito_redirect_uri: https://localhost:8912/auth/callback
  cognito_logout_redirect_uri: https://localhost:8912/

tapdb:
  env: dev
  client_id: bloom
  database_name: bloom
  config_path: /Users/<you>/.config/tapdb/bloom/bloom-bringup/tapdb-config.yaml
```

### 5. Verify before starting

```bash
source ./activate bringup
bloom config status
bloom config doctor
```

Important:

- do not rely on `BLOOM_AUTH__...` env vars for normal setup
- do not use `BLOOM_OAUTH=no` as the default local workflow
- exact callback and logout URLs matter; mismatches commonly show up as Hosted UI redirect/logout failures

## Health And Observability Checks

Anonymous-ish probe checks:

```bash
curl -k https://127.0.0.1:8912/healthz
curl -k https://127.0.0.1:8912/readyz
curl -k https://127.0.0.1:8912/health/metrics
```

Authenticated health surfaces:

```bash
curl -k https://127.0.0.1:8912/health \
  -H "Authorization: Bearer <blm-token>"

curl -k https://127.0.0.1:8912/db_health \
  -H "Authorization: Bearer <blm-token>"
```

Useful authenticated observability paths:

- `/obs_services`
- `/api_health`
- `/endpoint_health`
- `/db_health`
- `/api/anomalies`
- `/my_health`
- `/auth_health`

## Focused Test Recipes

Run a narrow unit/API target without tripping the repo-wide coverage gate:

```bash
source ./activate bringup
pytest --no-cov tests/test_execution_queue_api.py -q
pytest --no-cov tests/test_api_auth_rbac.py -q
pytest --no-cov tests/test_graph_viewer_api.py -q
```

Run the committed browser auth E2E tests:

```bash
source ./activate bringup
E2E_USER_PASSWORD=... pytest tests/e2e/test_auth_e2e.py -m e2e
```

Run broader checks:

```bash
source ./activate bringup
ruff check bloom_lims tests
pytest -q
```

Remember that plain `pytest` will enforce the repo's current coverage gate unless you opt out with `--no-cov` for focused runs.

## API Smoke Examples

Check auth context:

```bash
curl -k https://localhost:8912/api/v1/auth/me \
  -H "Authorization: Bearer <blm-token>"
```

Run search v2:

```bash
curl -k https://localhost:8912/api/v1/search/v2/query \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{"query":"sample","record_types":["instance"],"page":1,"page_size":25}'
```

Register an execution worker:

```bash
curl -k https://localhost:8912/api/v1/execution/actions/register-worker \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_key": "worker://demo/local-1",
    "display_name": "Local Demo Worker",
    "worker_type": "SERVICE",
    "status": "ONLINE"
  }'
```

## Diagnose Startup Failures

The fastest supported debug loop is:

```bash
source ./activate bringup
bloom config doctor
bloom config status
bloom server start --port 8912
bloom server logs
```

If startup aborts immediately, Bloom is usually telling you that one of these is missing:

- TapDB namespace config
- Cognito pool/client/domain/redirect config
- a writable runtime/storage path

## Troubleshooting

### Missing Cognito config

Symptoms:

- `bloom config doctor` warns that `auth.cognito_*` fields are missing
- server startup aborts with missing required configuration

Fix:

- populate the deployment-scoped Bloom YAML
- populate the TapDB namespace config through `tapdb db-config update`

### Conda environment mismatch

Symptoms:

- doctor warns you are not in the expected Bloom conda env

Fix:

- use `source ./activate <deploy-name>`
- current Bloom expects `BLOOM-<deploy-name>`, not a single hard-coded `BLOOM` env name

### Local TapDB runtime issues

Symptoms:

- readiness fails
- DB health fails
- GUI routes block on missing DB access

Fix:

```bash
source ./activate bringup
bloom db build --target local
bloom config doctor
```

### Logout or callback URL mismatch

Symptoms:

- Cognito error pages during login or logout
- redirect to the wrong host or path

Fix:

- set the exact callback URL and logout URL in both:
  - Bloom YAML
  - TapDB namespace config

For local HTTPS the expected pair is usually:

```text
https://localhost:8912/auth/callback
https://localhost:8912/
```

### Upload directory problems

Symptoms:

- doctor warns that the upload directory does not exist or is not writable

Fix:

- if you use the default, Bloom now creates the deployment-scoped upload directory automatically
- if you override it, make sure the custom path exists and is writable by the current process

Default pattern:

```text
~/.config/tapdb/bloom/bloom-<deploy-name>/<tapdb-env>/uploads
```

### Older docs or tooling still mention `bloom db init`

Symptoms:

- you see mixed guidance between `init` and `build`

Fix:

- use `bloom db build --target local`
- treat repo-local Bloom CLI help and these docs as authoritative

## Where To Go Next

- [architecture.md](architecture.md)
- [apis.md](apis.md)
- [gui.md](gui.md)
- [becoming_a_discoverable_service.md](becoming_a_discoverable_service.md)
