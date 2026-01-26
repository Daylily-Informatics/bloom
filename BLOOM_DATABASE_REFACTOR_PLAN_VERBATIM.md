# BLOOM Database Refactor Plan (Verbatim)

---

## 1. High-level summary (≤10 bullets)

Replace BLOOM’s internal TAPDB ORM + schema bootstrap (bloom_lims/db.py, postgres_schema_v3.sql, install scripts) with daylily-tapdb as the single DB implementation.

Keep BLOOM code stable by adding a thin compatibility shim that maps BLOOM’s field names (super_type, btype, b_sub_type) onto TapDB’s (category, type, subtype) via SQLAlchemy synonyms.

Preserve BLOOM’s BLOOMdb3 interface (engine/session/Base/classes/transaction) but back it with TapDB models.

Switch DB bootstrap to TapDB schema (schema/tapdb_schema.sql) and add BLOOM’s missing prefix sequences (CX/MX/EX/…); no live migration, just correct fresh-schema setup.

Do not redesign domain logic; refactor is mechanical: imports, schema bootstrap, and compatibility aliasing.

Handle the one real API gap: BLOOM references Base.classes.file_set_instance but daylily-tapdb doesn’t define it → provide an alias mapping file_set_instance → file_instance.

Update references to postgres_schema_v3.sql in scripts/docs/migrations to the new schema source.

Validate incrementally: imports compile → DB connects → schema applies → seed works → tests/CLI/API smoke.

---

## 2. Internal → TapDB mapping table

Goal: “bloom.internal.X → tapdb.Y” with concrete module/class targets.

BLOOM internal (current)	Replace with (TapDB)	Notes
bloom_lims/db.py: Base (declarative base)	daylily_tapdb.models.base.Base	Used by Alembic target_metadata.
bloom_lims/db.py: bloom_core	daylily_tapdb.models.base.tapdb_core (aliased as bloom_core)	BLOOM’s abstract base becomes TapDB’s.
bloom_lims/db.py: generic_template + typed templates	daylily_tapdb.models.template.*	Same table name; TapDB uses category/type/subtype.
bloom_lims/db.py: generic_instance + typed instances	daylily_tapdb.models.instance.*	Same; alias old field names.
bloom_lims/db.py: generic_instance_lineage + typed lineages	daylily_tapdb.models.lineage.*	Same; alias old field names.
bloom_lims/db.py: audit_log (currently automapped only)	daylily_tapdb.models.audit.audit_log	Explicit model exists in TapDB.
bloom_lims/db.py: BLOOMdb3	bloom_lims/tapdb_adapter.py: BLOOMdb3 wrapping TapDB models	Preserve interface; implementation swaps.
bloom_lims/env/postgres_schema_v3.sql	daylily-tapdb/schema/tapdb_schema.sql	BLOOM schema has hardcoded prefix switch; TapDB uses prefix sequences.
bloom_lims/env/install_postgres.sh uses postgres_schema_v3.sql	Update to apply TapDB schema + BLOOM prefix sequences	No data migration; just “fresh DB should be TapDB schema”.
seed_db_containersGeneric.py prefix check via grep ... THEN	Remove/replace with “ensure prefix sequences exist”	TapDB schema has no CASE statement to grep.
bloom_lims/core/cached_repository.py	(Optional) daylily_tapdb.templates.manager.TemplateManager	Not required for the DB swap; keep BLOOM logic unless you choose to fold this in later.

---

## 3. Stepwise refactor plan (numbered phases)

### Phase 0 — Baseline & dependency wiring (small, reversible)

Goal: Make daylily_tapdb importable from bloom.

Changes

bloom_env.yaml: add daylily-tapdb as a pip dependency.

Recommended for this refactor: editable install pointing at the sibling repo:

-e ../daylily-tapdb

requirements.txt (optional but helpful): add -e ../daylily-tapdb or a note.

(Optional) README.md: document the dependency expectation.

Rationale

Everything else is blocked until bloom can import TapDB.

Validation

python -c "import daylily_tapdb; print(daylily_tapdb.__version__ if hasattr(daylily_tapdb,'__version__') else 'ok')"

### Phase 1 — Introduce a BLOOM↔TapDB adapter module (no call sites changed yet)

Goal: Implement a stable, testable shim without touching existing code paths.

Add

New file: bloom_lims/tapdb_adapter.py

What goes in it

Re-export TapDB ORM types that bloom expects:

Base, tapdb_core (aliased), generic_template, generic_instance, generic_instance_lineage, typed variants, and audit_log.

Compatibility layer for field names:

Add SQLAlchemy synonyms:

super_type ↔ category

btype ↔ type

b_sub_type ↔ subtype

Apply to generic_template, generic_instance, generic_instance_lineage and all typed subclasses (or apply to the base class and rely on inheritance).

Compatibility layer for missing polymorphic classes referenced by BLOOM:

Alias:

file_set_template = file_template

file_reference_template = file_template

file_set_instance = file_instance

file_reference_instance = file_instance

file_set_instance_lineage = file_instance_lineage

file_reference_instance_lineage = file_instance_lineage

This is required because BLOOM references Base.classes.file_set_instance (see bloom_lims/domain/files.py) but TapDB does not define that subclass.

A drop-in BLOOMdb3 that preserves bloom’s API but registers TapDB models:

Preserve constructor signature defaults: db bloom, port 5445, username/password bloom.

Preserve members: engine, _Session, session, Base (automap-like), transaction(), new_session(), close().

In _register_orm_classes(), register TapDB models into self.Base.classes.* exactly like bloom did.

Rationale

This isolates all “API mismatch” logic to one module and keeps future diffs localized.

Validation

python -c "from bloom_lims.tapdb_adapter import BLOOMdb3, generic_instance; print(BLOOMdb3, generic_instance)" should import/compile.

---

### Phase 2 — Flip bloom’s public DB module to delegate to TapDB (core refactor)

Goal: Make from bloom_lims.db import BLOOMdb3 use TapDB-backed implementation, without touching all call sites.

Changes

Move legacy code aside:

Rename current bloom_lims/db.py → bloom_lims/db_legacy.py

Create a new bloom_lims/db.py that becomes a thin façade:

Re-export everything bloom expects from bloom_lims.tapdb_adapter.

Keep symbol names identical (BLOOMdb3, Base, generic_template, etc).

Rationale

This is the mechanical switch-over point. All imports stay stable.

Validation

python -c "from bloom_lims.db import BLOOMdb3; print(BLOOMdb3)"

python -m compileall bloom_lims

---

### Phase 3 — Schema/bootstrap switch: BLOOM now initializes DB via TapDB schema

Goal: Remove/deprecate BLOOM’s internal schema as the bootstrap source, and ensure fresh DBs work with TapDB’s trigger logic.

Changes

bloom_lims/env/install_postgres.sh

Replace the envsubst < bloom_lims/env/postgres_schema_v3.sql | psql ... line with:

apply TapDB schema: .../daylily-tapdb/schema/tapdb_schema.sql

apply bloom-specific prefix sequences (see next file)

Introduce environment variables for paths so it’s not hardcoded:

TAPDB_SCHEMA_SQL default: ../daylily-tapdb/schema/tapdb_schema.sql

Add new file: bloom_lims/env/bloom_prefix_sequences.sql

CREATE SEQUENCE IF NOT EXISTS <lower(prefix)>_instance_seq; for every prefix in BLOOM metadata:

CX, CWX, MX, MRX, MCX, EX, WX, WSX, QX, XX, DX, TRX, AY, AX, FG, FI, FS, FX, SX, EV, GX

(Yes, some are already in TapDB schema; IF NOT EXISTS makes this safe.)

Deprecate or delete bloom_lims/env/postgres_schema_v3.sql

Prefer delete at the end (Phase 5), but you can mark deprecated first if you want an intermediate PR.

Why this is required

TapDB’s set_generic_instance_euid() requires a per-prefix sequence named "<prefix>_instance_seq"; BLOOM used a hardcoded CASE expression instead. Without sequences, inserts will fail.

Validation

Run DB bootstrap:

./clear_and_rebuild_postgres.sh (after updating scripts)

Connect and run a minimal insert smoke:

python -c "from bloom_lims.db import BLOOMdb3; b=BLOOMdb3(); print(b.session.execute('select 1').scalar())"

---

### Phase 4 — Update seed scripts + docs that assume the old schema

Goal: Remove references to bloom’s old schema implementation.

Changes

seed_db_containersGeneric.py

Remove the old prefix check:

grep ... "'{obj_prefix}' THEN" bloom_lims/env/postgres_schema_v3.sql

Replace with either:

No check (best if Phase 3 ensures sequences), or

A direct “create sequence if missing” SQL executed via the session (acceptable, but less clean than Phase 3).

Docs + migration messaging

Update references:

bloom_lims/migrations/versions/20241223_0001_initial_baseline.py

bloom_lims/migrations/__init__.py

bloom_lims/migrations/utils.py

README.md, BLOOM_SPECIFICATION.md

Replace “created by postgres_schema_v3.sql” with “created by TapDB schema (tapdb_schema.sql)”.

Validation

Seed script runs without schema grep errors.

Template queries return expected rows (whatever your test suite expects).

---

### Phase 5 — Remove internal implementation (final cleanup, enforce single source)

Goal: Ensure no internal graph DB code remains in bloom.

Changes

Delete bloom_lims/db_legacy.py (after verifying it’s unused).

Delete bloom_lims/env/postgres_schema_v3.sql.

Remove any now-unused imports/notes referencing the legacy implementation.

Validation

grep -R "postgres_schema_v3.sql" -n returns zero matches (or only historical docs you intentionally kept).

pytest (or your normal test command) passes.

---

## 4. Adapter / shim design (required)

Location

bloom_lims/tapdb_adapter.py

Responsibilities

Field name translation

BLOOM uses: super_type, btype, b_sub_type

TapDB uses: category, type, subtype

Implement via SQLAlchemy synonym() so:

Existing bloom code doesn’t need a global rename.

Queries like Model.super_type == "container" still compile and hit the right underlying column (category).

Class name compatibility for Base.classes

BLOOM assumes bdb.Base.classes.<name> exists for:

generic_* and typed <domain>_*

Plus BLOOM-only names like file_set_instance

Implement by explicitly registering:

TapDB models under expected names

Aliases (file_set_instance → file_instance) to satisfy existing bloom call sites

BLOOMdb3 API preservation

Keep BLOOMdb3 constructor args, defaults, members, and transaction semantics.

Under the hood:

Use SQLAlchemy engine/session as before

Register TapDB models into .Base.classes

Pass-through vs translated

Pass-through

Table names: generic_template, generic_instance, generic_instance_lineage

Relationship attributes: parent_instance, child_instance, etc (TapDB defines these)

json_addl, uuid, euid, created_dt, modified_dt, is_deleted, etc

Translated

super_type ↔ category

btype ↔ type

b_sub_type ↔ subtype

file_set_* and file_reference_* classes → alias to TapDB file_*

Critical note (worth stating to Augment)

This shim is intentionally thin and mechanical.

It should not introduce new behavior, only name/shape compatibility.

---

## 5. Augment execution checklist (copy/paste friendly)

Phase 0

Edit bloom_env.yaml: add pip dep for TapDB (recommended: -e ../daylily-tapdb)

(Optional) Edit requirements.txt: add same editable dep line

Phase 1

Create bloom_lims/tapdb_adapter.py

Import TapDB models (daylily_tapdb.models.*)

Apply synonyms for super_type/btype/b_sub_type

Define/alias missing BLOOM class names (file_set_instance, etc)

Implement BLOOMdb3 wrapper and _register_orm_classes() to populate self.Base.classes.*

Add/adjust __all__ exports to match bloom’s existing public surface area

Phase 2

Rename bloom_lims/db.py → bloom_lims/db_legacy.py

Create new bloom_lims/db.py that re-exports:

from bloom_lims.tapdb_adapter import BLOOMdb3, Base, tapdb_core as bloom_core, ...

Ensure bloom_lims/migrations/env.py still imports Base, generic_template, generic_instance, generic_instance_lineage from bloom_lims.db unchanged

Phase 3

Create bloom_lims/env/bloom_prefix_sequences.sql with CREATE SEQUENCE IF NOT EXISTS ... for every prefix in bloom_lims/config/*/metadata.json

Edit bloom_lims/env/install_postgres.sh:

Apply TapDB schema (path via $TAPDB_SCHEMA_SQL)

Apply bloom prefix sequences SQL

(Optional) Update clear_and_rebuild_postgres.sh only if it hardcodes schema names (currently it just calls install script)

Phase 4

Edit seed_db_containersGeneric.py:

Remove schema grep ... THEN logic

Rely on sequences created in Phase 3

Update references to postgres_schema_v3.sql in:

bloom_lims/migrations/versions/20241223_0001_initial_baseline.py

bloom_lims/migrations/__init__.py

bloom_lims/migrations/utils.py

README.md, BLOOM_SPECIFICATION.md

Phase 5

Delete bloom_lims/db_legacy.py

Delete bloom_lims/env/postgres_schema_v3.sql

Run a repo-wide search to ensure no lingering imports/docs reference the removed files

---

## 6. Optional cleanup or simplification opportunities (do only after refactor is stable)

Fix the file_set_instance semantic ambiguity (currently BLOOM likely creates file-set instances as file_instance via polymorphic_discriminator derivation). If you want true polymorphic subclasses per btype, that’s a separate (non-mechanical) change—don’t mix it into this refactor.

Stop using automap reflection in BLOOMdb3 and replace .Base.classes with a cheap namespace object. This would reduce startup time and remove DB reflection dependency; again, optional after stabilization.

Make install_postgres.sh and clear_and_rebuild_postgres.sh POSIX-shell clean (they currently assume zsh options). Not required for the DB swap.

---

## Do this next

Implement Phase 1 + Phase 2 first (adapter + db.py flip) and ensure the repo imports/compiles end-to-end.

Then implement Phase 3 (TapDB schema bootstrap + prefix sequences) so EUID generation doesn’t break.

Only after that, clean up docs/legacy files (Phase 4–5).

