# Bloom LIMS — Agent Rules

## Entry Point — ALWAYS DO THIS FIRST
```
source bloom_activate.sh
```
This activates the `BLOOM` conda env AND exposes the `bloom` CLI. **The activate script IS the entry point. The CLI IS the interface. Nothing else.**

## Setup
- Activate: `source bloom_activate.sh`
- Conda env: `BLOOM`
- CLI: `bloom` (db, gui, config, info, status, doctor, shell, logs)
- DB port: 5445 (local Postgres via conda, NOT Docker)

## Database Operations — USE THE CLI
```
bloom db init        # Initialize from scratch
bloom db start       # Start PostgreSQL
bloom db stop        # Stop PostgreSQL
bloom db status      # Check if running
bloom db seed        # Load template JSON files
bloom db reset -y    # Drop and rebuild (DESTRUCTIVE)
bloom db shell       # Open psql
bloom db migrate     # Run migrations
```

Do NOT run `install_postgres.sh` directly. Do NOT run raw `pg_ctl`, `initdb`, or `createdb`.

## Architecture
- Uses TapDB as the underlying database framework (`pip install -e ../daylily-tapdb`)
- Object types defined via JSON templates in `bloom_lims/config/{category}/{type}.json`
- Templates seeded into `generic_template` rows, instantiated via `create_instances(template_euid)`
- Do NOT create dedicated Python domain classes for specific object types
- Use the existing generic domain layer (`BloomObj`, `BloomContent`, `BloomContainer`, etc.)

## Testing
```
source bloom_activate.sh
bloom db start       # DB must be running
pytest tests/ -v     # Full suite
```

## Key Test: Accessioning Workflow
`tests/test_create_acc_workflows.py` walks the entire accessioning pipeline end-to-end.
`smoke_exams/accession_extract_qant.py` is the integration smoke test.
Run and understand these BEFORE modifying any workflow-related code.

## PHI Boundary
Bloom is PHI-free. No patient names, DOBs, SSNs. Only Bloom EUIDs and links to Atlas EUIDs.

