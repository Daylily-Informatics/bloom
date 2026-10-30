# Bloom on TapDB 10.1.3

This guide describes the Bloom 10.0.3 source release. The accepted production migration is recorded separately in [its completed ledger](plans/20260911T150553Z_bloom_tapdb_10_1_migration_ledger.md); it must not be replayed as a startup or release step.

## Runtime contract

- `pyproject.toml` pins `daylily-tapdb[aurora,gui]==10.1.3` and `daylily-auth-cognito==2.1.5`.
- `container_entry.py` requires an existing absolute `BLOOM_CONFIG_PATH`, explicit `HOST` and `PORT`, initializes Bloom CLI context and TapDB `set_cli_context`, and calls `_verify_existing_tapdb` before starting the foreground server.
- `_verify_existing_tapdb` checks the released Bloom template requirements and the native opaque and TapDB-object external-reference templates. It does not seed or migrate them.
- `BLOOMdb3` uses TapDB `connection_role="runtime"` with explicit owner, domain, tenant, schema and config identity. Production runtime sessions use the constrained runtime principal, not the operator login.
- Schema migration, required template preparation and principal bootstrap/binding are operator operations completed before runtime startup. `bloom db build` accepts only `--target local`; its local lifecycle is not an Aurora migration procedure.

Relevant source: [container entrypoint](../bloom_lims/container_entry.py), [config](../bloom_lims/config.py), [adapter](../bloom_lims/tapdb_adapter.py), [database CLI](../bloom_lims/cli/db.py).

## Configuration and identity

Set `BLOOM_DEPLOYMENT_CODE` explicitly before importing or invoking Bloom. Existing code also accepts `DEPLOYMENT_CODE` and `LSMC_DEPLOYMENT_CODE`; activation does not export any of them. Use `BLOOM_CONFIG_PATH` as an absolute service-config file and an explicit `XDG_CONFIG_HOME` for CLI state/config locations. The YAML supplies:

- TapDB `client_id`, logical `database_name`, physical database and schema;
- `owner_repo_name`, domain and exact absolute config/registry paths;
- storage upload directory, authentication and public origin/callback settings.

The recorded production deployment uses logical database `bloom-day`, owner `bloom`, domain `M`, physical database `tapdb_bloom_prod`, schema `tapdb_bloom_lsmcok1_local`, and runtime role `bloom_runtime_10`. These are deployment-specific facts, not defaults for a new deployment. Keep runtime credentials and operator credentials separate and never commit their values.

## Immutable templates and durable data

Loaded template properties, schemas, semantic coordinates and bindings are immutable. Introduce a new template version for changed semantics. A reviewed migration may update bookkeeping and add required definitions without overwriting historical ones. Deleted or retired templates remain historical; do not reactivate or semantically rewrite them as part of routine migration.

`bloom db seed` calls the native seed path with `overwrite=False`. Existing maintenance commands `db refresh-templates` and `db build --force` still select overwrite behavior, and `db reset`/`db nuke` are destructive. Their existence is not permission to use them on loaded production templates. They are not production migration or docs-release steps.

Preserve stored UID/EUID, prefix, owner/issuer, domain, tenant, creation identity, deleted history, audit records and authoritative `generic_instance_lineage`. Never derive an existing EUID again from the current template. Cross-service relationships use typed external-reference objects plus lineage; copied identifier strings or graph metadata are not authoritative edges.

The completed migration preserved the historical 950 prefix/template differences and 186 BGX identities. Its approved conversion archived only 111 graph entries with matching lineage and retained 282 unresolved entries. These are receipt facts, not constants or expected counts for future databases.

## Sequence protection and recovery

A first resumed allocation must exceed applicable stored values, source-next values, reservations and failed-attempt/recovery exposures, including dormant generators. Preserve increment, alignment, bounds, cache and ownership constraints.

Verify a completed advancement against the prior plan floors. Newly reserved values become future recovery floors; do not advance repeatedly to exceed the reservation the previous advancement just created. Retain native receipts and external journals, including failed-attempt exposures. Deduplicate only identical `(name, value, source)` records.

A parser or transport failure is not evidence that a database operation failed. Inspect its terminal native receipt/journal and use native reconciliation for ambiguity. Never replay a committed schema migration or blindly recreate an identity/token. TapDB `operator_connection` encloses one transaction; an inner ORM session commit is not proof that the outer transaction committed.

The accepted migration advanced all 66 inventoried allocators once and retained the final positions without advancing again. Runtime writes continue to allocate normally. Future recovery must preserve acknowledged writes and all retained exposures; after accepting writes, repair forward. Existing Aurora backups were accepted for this migration, and no new snapshots or dumps were created.

## Native graph and read-only consumers

The public TapDB web integration mounts `/api/dag/manifest`, `/api/dag/v2/object/{euid}`, `/api/dag/v2/data` and `/api/dag/v2/search`. Bloom requires successful mounting and valid advertisement at startup. `/obs_services` exposes `tapdb.dag_v2` and the exact `tapdb_dag_contract_version` value `dag:v2`. Consumers must not fall back to a v1 contract.

The embedded GUI defaults to `/tapdb` and uses a public host-session bridge: Bloom ADMIN maps to TapDB admin, other authenticated Bloom users map to TapDB user. The GUI is not globally restricted to Bloom ADMIN by a separate mount wrapper. TapDB applies its own route permissions. Bloom's `/dindex2` and `/api/v1/graph` remain separate Bloom-specific surfaces; neither is the native DAG v2 contract.

A persisted Bloom API token is constrained by both its owner's explicit Bloom role and its scope. `internal_ro` does not turn an ADMIN-only owner into a READ_ONLY owner. Kahlo's accepted reader has Bloom ownership, explicit READ_ONLY, `API_ACCESS` and native `BLOOM-READONLY` group codes, and an expiring `internal_ro` token. Role-group constants, CLI input validation and repository output use canonical uppercase group codes (for example `BLOOM-READONLY`). This is a code correction; existing group identities, memberships and stored explicit roles are not rewritten.

The recorded native credential helper is [bloom_kahlo_reader_prepare.py](../scripts/bloom_kahlo_reader_prepare.py). It is a target-bound migration artifact, not an idempotent setup command: exclusive output receipts and exact preconditions intentionally prevent blind reruns. Inspect prior state and receipts before any separately authorized repair. Token output stays in protected files; do not print it in logs or commit it.

## Release and follow-up boundaries

Use the [release procedure](how-tos.md#publish-a-documentation-release) for documentation-only tags. No migration, seed, principal rebinding, runtime probe, test run, image build or redeploy is needed for a docs change. Application releases and tests require their own authorized scope under [AGENTS.md](../AGENTS.md).

The [phase-2 backlog](plans/20260912T045329Z_bloom_phase_2_backlog.md) and [approved execution ledger](plans/20260912T053000Z_bloom_phase_2_execution_ledger.md) separate implemented fixes, investigation outcomes and deferred items. Image digests and immutable release receipts control provenance; a stale footer is not evidence of a different running image. No phase-2 item is automatically selected by this documentation release.

## Phase-2 lifecycle and provenance corrections

`RequestDatabaseMiddleware` owns every Bloom adapter created during an HTTP request, including sync handlers. It closes adapters after the complete ASGI response and its response background tasks. Adapter close releases primary and additional sessions and rolls back unfinished transactions; route/domain code still owns explicit write commits. CLI and standalone tasks retain their own context-manager/close responsibility.

Bloom container builds require `BLOOM_BUILD_BRANCH`, `BLOOM_BUILD_SHA` and the explicit setuptools-scm release version. The image exports these as source metadata for the footer. A checkout resolves its own Git state; images must not guess source identity. Kahlo 8.0.1 already embeds correct source provenance; Dayhoff must not override it with a deployment image digest or stale version.

On 2026-09-12 [TapDB issue #111](https://github.com/Daylily-Informatics/daylily-tapdb/issues/111) remained OPEN. Its original Bloom-blocked description is historical: accepted TapDB 10.1.3 additive versioned XRF behavior resolved that deployment blocker without overwriting historical definitions. Bloom requires no additional upgrade or conversion for this issue. Upstream issue closure and broader lifecycle documentation remain the upstream owner's decision.

The phase-2 read-only investigation found all 282 remaining graph entries on 72 active Bloom rows lack linked legacy reference evidence for the migration's exact match. Retain them unchanged as historical metadata; do not promote them into authoritative lineage or discard them without a separate data decision. No remote service was contacted.
