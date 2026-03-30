# TAPDB CLI Specification (Bloom Integration)

This document defines the TapDB command surface Bloom relies on.

## Required Context

```bash
export TAPDB_ENV=dev
export TAPDB_DATABASE_NAME=bloom
export AWS_PROFILE=lsmc
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
```

For namespace isolation with multiple apps under one user, prefer:
- `~/.config/tapdb/tapdb-config-bloom.yaml`

## Activation

```bash
source ../../daylily-tapdb/activate
```

## Bootstrap

```bash
# local postgres runtime + schema + seed path
python -m daylily_tapdb.cli bootstrap local --no-gui

# aurora bootstrap path
python -m daylily_tapdb.cli bootstrap aurora --cluster <cluster-id> --region us-west-2 --no-gui
```

## PostgreSQL Runtime (`tapdb pg`)

```bash
python -m daylily_tapdb.cli pg init dev
python -m daylily_tapdb.cli pg start-local dev
python -m daylily_tapdb.cli pg stop-local dev
python -m daylily_tapdb.cli pg status
python -m daylily_tapdb.cli pg logs
```

## Database/Schema/Data (`tapdb db`)

```bash
python -m daylily_tapdb.cli db create dev
python -m daylily_tapdb.cli db setup dev
python -m daylily_tapdb.cli db schema status dev
python -m daylily_tapdb.cli db schema migrate dev
python -m daylily_tapdb.cli db schema reset dev --force
python -m daylily_tapdb.cli db data seed dev
python -m daylily_tapdb.cli db data backup dev
python -m daylily_tapdb.cli db data restore dev
```

## Config and Cognito Ownership

```bash
python -m daylily_tapdb.cli --client-id bloom --database-name bloom config init \
  --env dev --db-port dev=5566 --ui-port dev=8912
python -m daylily_tapdb.cli --client-id bloom --database-name bloom config update \
  --env dev --audit-log-euid-prefix audit.bloom --support-email support@daylilyinformatics.com
daycog config create-all --pool-name daylily-ursa-users --region us-west-2 --default-client atlas
python -m daylily_tapdb.cli --client-id bloom --database-name bloom config update \
  --env dev \
  --cognito-user-pool-id us-west-2_5r8gIqV5P \
  --cognito-app-client-id 6j2pa8nr9ve19aeuhnb1ocpl2r \
  --cognito-client-name bloom \
  --cognito-region us-west-2 \
  --cognito-domain daylily-ursa-5r8giqv5p.auth.us-west-2.amazoncognito.com \
  --cognito-callback-url https://localhost:8912/auth/callback \
  --cognito-logout-url https://localhost:8912/
```

## Bloom CLI Mapping

Bloom keeps only Bloom-specific DB commands:
- `bloom db init`
- `bloom db seed`
- `bloom db reset`
- `bloom db nuke`

`bloom db nuke` is a delete-only passthrough to `tapdb db schema reset` and does not seed, setup, init pg, or start pg.

Use `tapdb ...` directly for shared runtime/schema/database lifecycle. Use `daycog ...` directly for Cognito pool/app/user lifecycle.

### Assay Extraction Pipeline Reseed (Destructive)

For assay extraction queue/action rollouts (HLA 1.2 + Carrier 3.9), use:

```bash
bloom db reset -y
bloom db seed
bloom server start
```

Then verify newly seeded assay workflows include queue steps:
- `extraction-batch-eligible`
- `blood-to-gdna-extraction-eligible`
- `buccal-to-gdna-extraction-eligible`
- `input-gdna-normalization-eligible`
- `illumina-novaseq-libprep-eligible`
- `ont-libprep-eligible`

## Notes

- Bloom does not own Alembic migration artifacts.
- Bloom does not own a backup CLI.
- TapDB is authoritative for DB runtime, schema, and backup/restore operations.
- Bloom unified search v2 (`/api/v1/search/v2/*`, `/search`) uses TapDB-backed ORM access through `BLOOMdb3`; no direct PostgreSQL lifecycle calls are used for search.

## Auth/RBAC Runtime Notes

Bloom auth group/token metadata is persisted in TapDB generic templates:
- `bloom/auth/user-group/1.0/`
- `bloom/auth/user-group-revision/1.0/`
- `bloom/auth/user-group-membership/1.0/`
- `bloom/auth/user-api-token/1.0/`
- `bloom/auth/user-api-token-revision/1.0/`
- `bloom/auth/user-api-token-usage-log/1.0/`

System groups are automatically bootstrapped on demand:
- `bloom-readonly`
- `bloom-readwrite`
- `bloom-admin`
- `bloom-rnd`
- `bloom-clinical`
- `bloom-auditor`
- `API_ACCESS`
- `ENABLE_ATLAS_API`
- `ENABLE_URSA_API`

To test legacy API key behavior in local development only:

```bash
export BLOOM_ALLOW_LEGACY_API_KEY=true
```

For Atlas read integration runtime:

```bash
export BLOOM_ATLAS__BASE_URL=https://atlas.example.org
export BLOOM_ATLAS__TOKEN=<atlas-service-token>
export BLOOM_ATLAS__TIMEOUT_SECONDS=10
export BLOOM_ATLAS__CACHE_TTL_SECONDS=300
export BLOOM_ATLAS__VERIFY_SSL=true
```
