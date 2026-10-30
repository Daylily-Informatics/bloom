# Bloom Discoverability and Deployment Contract

Bloom exposes service identity and native graph capabilities through authenticated observability routes. Dayhoff supplies explicit deployment configuration and selects the service image; Kahlo consumes Bloom's advertised native DAG contract. This document describes Bloom's source contract, not an unverified snapshot of a sibling repository's catalog.

## Runtime entrypoint and configuration

The Bloom CLI entrypoint is `bloom_lims.cli:main`; registered command groups are listed in the [README](../README.md#cli-interface). Local activation uses `source ./activate <deploy-name>` and only prepares the environment. It does not seed config or export deployment identity.

The container entrypoint is `bloom_lims.container_entry`. It requires an existing absolute `BLOOM_CONFIG_PATH`, explicit `HOST` and `PORT`, initializes the Bloom and TapDB contexts, verifies existing templates and starts the foreground server. The usual Bloom service port is 8912, but the deployment must pass its actual port explicitly. Do not use a local bootstrap command as a production container startup action.

Schema migration, template preparation and runtime-principal setup happen before production startup. `bloom db build --target local` is limited to local preparation; it rejects Aurora. See [TapDB 10 operations](tapdb_10_operations.md).

## Authenticated discovery

Bloom exposes `/healthz`, `/readyz`, detailed `/health` routes and authenticated observability routes including `/obs_services`, `/api_health`, `/endpoint_health`, `/db_health`, `/my_health` and `/auth_health`.

`bloom_lims/observability.py` obtains graph capability data from the native mount advertisement. Consumers must retain both:

- the extension `tapdb.dag_v2`;
- `tapdb_dag_contract_version` with the exact value `dag:v2`.

The native `/api/dag/manifest` describes `/api/dag/v2/object/{euid}`, `/api/dag/v2/data` and `/api/dag/v2/search`. Do not substitute Bloom's `/api/v1/graph` helper surface when the native contract is missing or fails. Mounting the native surfaces is mandatory in `create_app`; an invalid advertisement aborts startup.

The embedded browser GUI defaults to `/tapdb`; its public host bridge consumes the existing Bloom session. It is distinct from service-token authentication for native DAG APIs.

## Kahlo read-only consumption

Kahlo needs an explicit Bloom target URL and Authorization credential, a persisted Bloom-owned user with an explicit READ_ONLY role, and an allowed `internal_ro` token. The accepted migration used native `API_ACCESS` and `BLOOM-READONLY` group codes. An ADMIN-only owner's token is not converted to READ_ONLY merely by narrowing the scope.

The migration's recorded Kahlo 8.0.1 correction preserves `tapdb_dag_contract_version` in its typed capability snapshot. A targeted Bloom-only poll advertised `dag:v2`, and the authenticated graph rendered six nodes and six edges with zero external jumps. Refer to the [completed ledger](plans/20260911T150553Z_bloom_tapdb_10_1_migration_ledger.md); do not repeat this operation during a docs-only release or turn a Bloom refresh into a fleet-wide action.

## Exposure and release ownership

Bloom is LSMC-internal only. Dayhoff owns approved-network ingress, service hostnames, TLS and broker routing. Do not infer public URLs from internal ports, add wildcard vhosts or expose Bloom globally. Each deployment supplies its own explicit namespace, configuration and credentials.

The recorded accepted production state is Bloom 10.0.1 / TapDB 10.1.3 at `https://bloom.day.lsmc.bio`, with Kahlo 8.0.1. A documentation tag does not update the Dayhoff pin or that running image. For authorized runtime changes, promote only selected containers using the exact tagged image digest and preserve sibling manifest entries.

Publish docs using the [working-branch tagged-release procedure](how-tos.md#publish-a-documentation-release). No tests or redeployment are implied. PR and merge work remains a separate action requiring the user's explicit request twice.
