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
source ./tapdb_activate.sh
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
python -m daylily_tapdb.cli db setup dev --include-workflow
python -m daylily_tapdb.cli db schema status dev
python -m daylily_tapdb.cli db schema migrate dev
python -m daylily_tapdb.cli db schema reset dev --force
python -m daylily_tapdb.cli db data seed dev --include-workflow
python -m daylily_tapdb.cli db data backup dev
python -m daylily_tapdb.cli db data restore dev
```

## Cognito (`tapdb cognito`)

```bash
python -m daylily_tapdb.cli cognito setup dev
python -m daylily_tapdb.cli cognito bind dev --pool-id <pool-id>
python -m daylily_tapdb.cli cognito status dev
python -m daylily_tapdb.cli cognito add-app dev --app-name bloom --callback-url https://localhost:8912/auth/callback --logout-url https://localhost:8912/
# Equivalent Bloom wrapper (always app-name=bloom):
bloom db auth-setup --port 8912 --region us-east-1
python -m daylily_tapdb.cli cognito add-user dev john@dyly.bio --password TestPass123!
```

## Bloom CLI Mapping

Bloom DB commands are wrappers around TapDB:
- `bloom db init`
- `bloom db start`
- `bloom db stop`
- `bloom db status`
- `bloom db migrate`
- `bloom db seed`
- `bloom db reset`

## Notes

- Bloom does not own Alembic migration artifacts.
- Bloom does not own a backup CLI.
- TapDB is authoritative for DB runtime, schema, and backup/restore operations.
- Bloom unified search v2 (`/api/v1/search/v2/*`, `/search`) uses TapDB-backed ORM access through `BLOOMdb3`; no direct PostgreSQL lifecycle calls are used for search.
