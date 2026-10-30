<!-- user-policy: tagged-production-first-20260912 -->
# User release policy — 2026-09-12

This explicit user instruction supersedes older release and test defaults in this file and in skills.

- Default to a tagged Git release from the current working branch, with no tests run. Commit the intended release changes and create an immutable annotated numeric version tag. Deploy the exact tagged revision/image only when runtime deployment is in scope. Documentation-only releases need no tests, package/container builds, Dayhoff pin changes or redeployment.
- Get the tagged release running in production first. After production is stable and the user accepts it, PR creation and branch merging are separate later work, requiring the user's explicit request twice for the specific action and scope. Never decide to open a PR, merge to main, or merge one branch into another on the user's behalf.
- Tests are off by default. Do not initiate pytest, lint, coverage, comprehensive tests, or a CI/test campaign unless the user explicitly requests that action and scope twice. Reuse existing valid evidence. Already-requested runtime availability/stability observations do not authorize a new test campaign.
- Keep builds and deployments scoped to the selected service and final tagged revision. Do not trigger a full Dayhoff deployment for each code edit, change sibling services, or add intermediate build/test stages on your own.
- Preserve unrelated dirty work and existing production identities. Never move or overwrite a pushed release tag. Use a working branch for follow-up changes; do not turn release publication into a main-branch merge workflow.
- If this policy is violated, record the concrete action and available elapsed-time, token-usage, and billing evidence. The user may request monthly lost-time/token/cost summaries for an OpenAI credit petition; do not invent costs, imply a credit entitlement, or start recurring reporting without an explicit request.

<!-- end-user-policy: tagged-production-first-20260912 -->

# Shell Session Defaults

- Default to an interactive shell for shell work. On this Mac, use the user's default shell unless the user explicitly asks for another shell.
- For AWS EC2, ParallelCluster, and other remote Linux hosts, default to an interactive `bash` login shell as `ubuntu`. Do not use `root` unless the user explicitly grants permission for that specific work; use targeted `sudo` from `ubuntu` when escalation is required.
- For Daylily/DayOA/DAY-EC headnode workflow work, use an interactive `ubuntu` tmux/login-shell pane for controllers and workflow commands. Run setup as separate commands in that pane (`source dyoainit`, then `dy-a ...`, then `dy-r ...`) so aliases/functions are defined before use.
- SSM Run Command is for simple inspection or for writing helper scripts through the supported helpers. Do not launch workflow controllers or rely on `dy-*` aliases from non-interactive SSM scripts.

# Bloom CLI Policy

## Session Setup

For Bloom CLI/runtime work, activate the repo environment. Static documentation edits and Git release operations do not require activation or installing dependencies:

```bash
source ./activate <deploy-name>
```

Activation does not export the deployment code. Set `BLOOM_DEPLOYMENT_CODE`, an explicit absolute `BLOOM_CONFIG_PATH`, and `XDG_CONFIG_HOME` before invoking Bloom; populate the required TapDB and registry paths in YAML.

## Activate Contract

- `activate` must stay env-only: create the conda env if missing, activate it, and run exactly one `python -m pip install -e <repo-root>` on first create.
- Do not add config copying, TapDB env exports, loader-path mutation, pre-commit installs, Playwright installs, shell tool checks, or DB/bootstrap work back into `activate`.
- Keep config materialization in the supported config operation. Keep local database preparation in `bloom db build --target local`, and production Aurora migration/template/principal setup in explicitly authorized native operator operations. Never move them into activation or ordinary container startup.
- Every service config, TapDB config, and TapDB registry path must be passed explicitly as a full absolute file path.
- Do not guess TapDB config or registry paths from deployment code, `~/.config`, or repo-local defaults during runtime startup.
- If Bloom is missing an explicit path, fail hard and fix the caller or config source instead of synthesizing a fallback path.

## Dependency Boundary

- `environment.yaml` is only for Python/bootstrap/system packages.
- All Python libraries needed by the repo belong in `pyproject.toml` under `[project.dependencies]`.
- Do not reintroduce `pip:` blocks or Python package installs into `environment.yaml`.
- Do not add any secondary install set such as `.[dev]`, `.[test]`, `requirements-dev.txt`, or `[project.optional-dependencies]`.

## CLI Contract

- `bloom` and every declared console script must resolve from the activated conda env `bin/` directory.
- Document `bloom db build --target local` explicitly. The implementation defaults to local but rejects any non-local target; it is not an Aurora migration command.
- Bloom runtime and bootstrap commands must consume explicit absolute config file paths.
- Do not reintroduce service-config, TapDB config, or registry-path guessing from deployment names, `HOME`, `~/.config`, or silent fallback helpers.
- If Bloom is invoked by Dayhoff or another orchestrator, that caller must pass the full absolute `--config` path plus the full absolute TapDB config and registry paths Bloom needs.
- `bloom config init` may materialize the deployment-scoped YAML, but every later runtime/bootstrap path must fail hard when required explicit file paths are missing or non-absolute.

## Command Ownership

- Use `bloom ...` as the primary interface for normal Bloom work.
- MUST use Bloom's supported API/CLI surface for Bloom operations.
- Use `tapdb ...` only when Bloom explicitly delegates low-level DB/runtime lifecycle to TapDB.
- Use `daycog ...` only when Bloom explicitly delegates shared Cognito lifecycle to Daycog.

## No Circumvention Policy

- Do not bypass `bloom`, `tapdb`, or `daycog` with raw tools just because something is missing or broken.
- Do not treat direct `python -m ...`, raw `postgres`, raw AWS CLI mutations, or direct config-file edits as automatic fallbacks.
- Do not use temporary auth/runtime override hacks such as `BLOOM_OAUTH=no` or ad hoc `BLOOM_AUTH__*` values to force startup unless the user explicitly asks for that exact workaround.
- If the intended CLI path is broken or incomplete, stop, diagnose, and ask for permission before circumventing it.
- Prefer patience and repair of the intended CLI workflow over inventing a shortcut.

## Dayhoff Service Exposure Security

- Bloom is an LSMC-internal only Dayhoff service. Do not configure it as an approved-network customer/collaborator service.
- Do not add globally public Bloom ingress, wildcard/fallback vhosts, old callback aliases, inferred return URLs, or service-side host discovery.
- Bloom should consume explicit broker/service claims and explicit Dayhoff-generated service config. Do not infer customer network or tenant access locally.
- `kahlo`, `bloom`, and `zebra_day` are LSMC-internal only; `login`, `atlas`, `dewey`, and `ursa` are approved-network customer/collaborator services.
- Service-host certs use DNS-01 renewal; do not depend on HTTP-01 public reachability for Bloom service hosts.
- Future dev, test, and stage deployments must use their own approved-source lists, credentials, certificates, TapDB schemas, and tenant data, separate from production.

## Version Tags

- Use non-v semver tags for package releases, e.g. `2.0.19` or `5.0.21`, not `v2.0.19`.
- Commit first, then tag the exact clean release commit.
- Use annotated tags for release provenance: `git tag -a 2.0.19 -m "Release 2.0.19"`.
- Lightweight tags are acceptable only for scratch/internal marks, not package releases.
- Do not move or overwrite pushed version tags. If a pushed tag is wrong, cut the next patch version.
- If signing is configured and expected, use signed annotated tags: `git tag -s 2.0.19 -m "Release 2.0.19"`.
- Verify tag type with `git cat-file -t 2.0.18`; `tag` means annotated and `commit` means lightweight.

## Source and documentation contract

- Exact runtime dependencies come from `pyproject.toml`: TapDB `[aurora,gui]==10.1.3`, Cognito `2.1.5`, Python >=3.12. Bloom's version is derived by setuptools-scm; do not edit a generated version module to publish a tag.
- Registered Bloom-specific CLI families are `server`, `db`, `users`, `integrations`, `test`, `quality`, and additional `config` commands. The shared CLI supplies common commands. There are no registered `objects`, `templates`, `lineage`, `tokens` or `admin` CLI families; use the actual API/GUI surfaces.
- Container startup initializes the explicit TapDB CLI context and verifies existing template requirements. `BLOOMdb3` uses a runtime connection role. Migration, seeding and runtime-principal creation/binding are separate operator operations.
- The embedded public TapDB GUI defaults to `/tapdb`. Its host bridge maps Bloom ADMIN to TapDB admin and all other authenticated users to TapDB user; do not describe the whole mount as admin-only or claim it preserves separate READ_ONLY/READ_WRITE native GUI roles.
- Native DAG consumers use `/api/dag/v2/*` and `/api/dag/manifest`, advertised by `tapdb.dag_v2` plus exact `tapdb_dag_contract_version=dag:v2`. `/api/v1/graph` and `/dindex2` remain Bloom-specific surfaces; do not make them a native v1 fallback.
- Loaded template semantics are immutable; changed properties/schema require a new template version. Preserve historical bindings, stored UID/EUID/prefix/domain/issuer/tenant, deleted state, audit and authoritative lineage. Only reviewed bookkeeping updates may change existing templates during migration.
- Existing `db refresh-templates` and `db build --force` select overwrite behavior; `reset` and `nuke` are destructive. Do not turn those commands into a production migration recipe or a release prerequisite.
- Never invent EUID-shaped examples. Use `<persisted-object-euid>` placeholders or actual owning-service receipts. Typed external-reference objects plus `generic_instance_lineage` own durable cross-service relationships.
- Validate a completed sequence advancement against its prior plan floors. Retain newly reserved values and failed-attempt exposures as future recovery floors; never advance repeatedly just to exceed newly created reservations. Inspect native terminal receipts before retrying an ambiguous operation.
- Normal GETs may persist auth/audit objects. Do not assume browsing is write-free while freezing migration inputs.
- Keep current docs aligned with mounted routes and actual registration/config code. Preserve dated execution history; label archived docs as historical rather than treating them as present-day instructions.

## Documentation release procedure

1. Review current docs against the source in the intended working branch and preserve unrelated changes.
2. Stage only intended documentation/instruction paths, commit, and push that working branch.
3. Create and push the next unused annotated numeric tag at the clean release commit; create the GitHub tagged release with notes identifying the documentation-only scope.
4. Do not PR, merge, run tests/lint/coverage, build images/packages, publish to PyPI, update Dayhoff pins or redeploy unless separately requested. The existing no-tests and double-request policy above controls.
5. Distinguish the latest documentation tag from the last deployed application tag. The completed migration records production Bloom 10.0.1 / TapDB 10.1.3 and Kahlo 8.0.1; a documentation tag alone does not change that deployment.

## Deployed service acceptance

When runtime deployment is explicitly requested, confirm the selected service is running and the requested normal user flow works. Reuse valid migration/runtime evidence. Do not automatically initiate browser/permission/load test campaigns or collect new screenshots. Documentation-only work needs no production inspection or acceptance run.

Use [docs/tapdb_10_operations.md](docs/tapdb_10_operations.md), [docs/how-tos.md](docs/how-tos.md), the completed migration ledger and the separate phase-2 backlog for current operating boundaries. Do not add compatibility shims, auth bypasses, inferred deployment defaults or sibling-service changes to resolve an out-of-scope defect.

## Request cleanup and build provenance

- HTTP request scope owns Bloom adapters through `RequestDatabaseMiddleware`, including sessions created by `new_session`. Keep explicit domain commits; request teardown must close/rollback, never auto-commit pending work. Standalone operations still own explicit close/context management.
- Role-group constants and persistence/CLI boundaries use uppercase codes; do not add alternate group identities or rewrite existing memberships to fix casing.
- Container builds supply exact `BLOOM_BUILD_BRANCH`, `BLOOM_BUILD_SHA` and release version. Preserve image-owned source metadata; an image digest is not a Git commit.
