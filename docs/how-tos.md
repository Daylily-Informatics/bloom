# Bloom How-Tos

These instructions describe registered commands and the explicit configuration required by the current source. They are recipes, not authorization to mutate a database or run tests. Historical deployment ledgers are evidence of completed work, not scripts to replay.

## Prepare a local environment

From the intended checkout, replace every absolute path placeholder with the actual provisioned path:

```bash
export BLOOM_DEPLOYMENT_CODE=bringup
export XDG_CONFIG_HOME=/absolute/path/to/operator-config
export BLOOM_CONFIG_PATH=/absolute/path/to/bloom-config-bringup.yaml
source ./activate bringup
bloom --help
```

`activate` accepts one deployment name matching `^[A-Za-z0-9-]{2,8}$`, creates or activates `BLOOM-<deploy-name>`, and installs this checkout in editable mode only when it creates the environment. It does not export the deployment code, seed config, install additional tool sets or touch the database. If an existing environment points at another checkout, deliberately correct that binding before using it; activation does not reinstall it automatically. No activation/install is needed for static documentation or Git work.

## Configure Bloom explicitly

The shared CLI provides `bloom config init`, `path` and `edit`; Bloom additionally registers `config status`, `doctor` and `shell`. `config init` is a config-writing operation, not database bootstrap. Use it only when intentionally provisioning a config, then fill the actual deployment values before starting the service.

Bloom YAML must supply exact TapDB config and registry paths, namespace identity, schema/physical database, storage directory, auth settings and network origins. See [architecture](architecture.md#configuration) and [TapDB 10 operations](tapdb_10_operations.md). Do not use another deployment's files as defaults. Config status/doctor are optional diagnostics when requested, not mandatory release checks; keep their output private if it contains configuration details.

Authentication uses pinned `daylily-auth-cognito==2.1.5` and the configured Cognito or external broker mode. Use the existing deployment's exact callback/logout URLs and broker service identity. Shared Cognito lifecycle belongs to `daycog`; consult its installed help for an explicitly requested lifecycle operation. A Bloom docs release does not create clients, rotate keys or change OAuth settings.

## Local database preparation

Only for an intentionally provisioned local database, after explicit config is complete:

```bash
bloom db build --target local
```

The implementation delegates local PostgreSQL initialization/start, database/schema creation, templates and runtime-principal setup to TapDB. This command is not an Aurora migration procedure; `--target aurora` is rejected. `bloom db seed` uses `overwrite=False`. `refresh-templates`, `build --force`, `reset` and `nuke` must not be used to overwrite loaded production template semantics or repeat a completed migration. See [the preservation contract](tapdb_10_operations.md#immutable-templates-and-durable-data).

## Start an already-prepared local service

With explicit config and certificate settings in place:

```bash
bloom server start --port 8912
```

Registered lifecycle commands also include `server status`, `server logs` and `server stop`. A container uses `bloom_lims.container_entry`, requires explicit `HOST`/`PORT`, verifies existing TapDB requirements and starts the server in the foreground. Dayhoff owns the reverse proxy and production service promotion.

For an authorized deployment, confirm the requested service is running and normal sign-in/navigation works. Do not turn that into an automatic suite of API, browser, negative-permission, load or migration checks. Do not disable TLS verification or authentication to force a successful result.

## Use the API and GUI

- Human operations: [GUI routes](gui.md), including `/lab-actions` and `/tapdb`.
- Object/template/lineage operations: [API reference](apis.md). These are not registered CLI command families.
- Native consumer graphs: use `/api/dag/v2/*` from the authenticated discovery manifest, with exact `dag:v2` capability; no v1 fallback.
- User/token commands: `bloom users provision-local` and `bloom users issue-token`. Review explicit role, scope and group requirements first. The token command prints plaintext; direct output to a protected destination and never paste it into a ledger or commit.

Examples containing `<persisted-...-euid>` require an actual identifier returned by the owning service. Never substitute a made-up EUID. A GET may record an auth or audit object; do not assume it is write-free during maintenance.

## Publish a documentation release

The normal docs-only path is: edit docs and `AGENTS.md`, review them against source, commit selected paths on the current working branch, push the branch, create and push an annotated numeric tag, then create the GitHub release. The version comes from setuptools-scm; do not edit a generated version file.

Use the actual branch and next unused version. The placeholders below are intentionally not executable defaults:

```text
git add <explicit documentation paths>
git commit -m "Update Bloom documentation [skip ci]"
git push origin <current-working-branch>
git tag -a <next-version> -m "Release <next-version>: documentation update"
git push origin refs/tags/<next-version>
gh release create <next-version> --verify-tag --title "Bloom <next-version>" --notes-file <release-notes-file>
```

Do not move an existing tag. Do not create a PR or merge branches. No tests, lint, coverage, image/package build, PyPI publish, Dayhoff pin change or redeploy is implied by a docs-only GitHub release. CI currently targets pushes/PRs to `main`, not working-branch/tag pushes; inspect workflow triggers before assuming a future release behaves the same.

For runtime changes, deployment scope must be explicit and limited to the selected service image. Production stability does not automatically authorize a later merge. PRs, merges and test execution require the user's explicit request twice for the specific action/scope. Existing tests and prior receipts are reference material; do not run them by default.

## Troubleshoot only a demonstrated problem

Check the exact configured file, deployment identity and failing source path. Missing config must be corrected explicitly; do not add inferred paths, auth bypasses or compatibility shims. Container startup cannot repair missing templates/schema. Use a separately authorized native operator operation when preparation is required.

For a stalled migration operation, identify the existing transaction/lock and inspect its receipt before retrying. In the completed migration, idle runtime transactions blocked template preparation; stopping only Bloom during the accepted outage released them. This is historical evidence, not permission to terminate sessions or restart production during documentation work.

Current migration receipts and deferred issues are linked from the [README](../README.md).
