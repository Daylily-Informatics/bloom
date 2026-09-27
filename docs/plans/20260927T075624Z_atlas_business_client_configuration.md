# Bloom Atlas business-client configuration

## Current continuation state

Source-only addition requested by the resumed Atlas accession project. Runtime inspection on 2026-09-27 found `atlas.base_url` and the native DAG token configured, but `atlas.token` absent. No configuration changes, credentials, restart, build or deployment have been performed by this work. TapDB remains pinned at 10.1.4. Tests and final review are **WONT DO** by explicit user instruction. The existing migration/lifecycle helper is not to be executed.

The controlling ledger is in Dayhoff: `docs/plans/20260926T141228Z_accession_object_specification_ledger.md`. Atlas source is on `codex/accession-objects-20260927`. Preserve existing Bloom native-reference repair receipts and historical datasets.

## Supported operation added

```text
bloom integrations atlas configure-business-client \
  --config /absolute/existing/bloom-config.yaml \
  --base-url https://atlas.day.lsmc.bio \
  --organization-id UUID_FROM_RETAINED_ATLAS_ORGANIZATION \
  --token-file /absolute/private/atlas-business-token
```

The token must be an owning Atlas integration API-client credential. It is not the native DAG token, webhook HMAC secret, or another service's credential. The command reads a private regular file, validates the Atlas configuration without printing sensitive validation inputs, preserves all other YAML values, checks for an intervening file change, retains ownership, and atomically installs the updated configuration with mode 0600. Paths must be explicit and absolute. No database or template operation is included.

The running 10.0.12 CLI has `show` and `doctor`, but no `config set`; this supported command fills that gap instead of using direct configuration-file mutation as an unapproved fallback. Source publication and an eventual selected Bloom image/deployment remain separate from configuration completion. Do not deploy an intermediate image; include the command in the final approved tagged build on EC2.

## Remaining runtime steps

1. Preserve exact running image/config identities and the existing business credential if available; never rotate an unrelated client.
2. Supply a tenant-scoped Atlas integration token through the owning Atlas CLI/API and protected files; retain its actual persisted client identity without disclosing the secret.
3. Invoke this supported command from the final Bloom release, against the exact live mounted configuration.
4. Restart/recreate only Bloom with the selected final image; report startup/configuration separately from workflow acceptance.

No test fixture, historical repair, native package/schema change, PR or merge is part of this repair.
