# BLOOM Database Refactor Plan — Augment / VS Code Execution

> **Audience:** Augment Code running GPT‑5.2 in VS Code
> **Constraint:** Mechanical refactor only. No semantic redesign.
> **Success condition:** BLOOM imports, boots, seeds, and runs entirely on daylily‑tapdb.

---

## Mission

Replace BLOOM’s internal DB implementation with **daylily‑tapdb** while preserving:

- All existing BLOOM imports
- `BLOOMdb3` public API
- Field names used throughout BLOOM code
- Runtime behavior (EUID generation, polymorphism, transactions)

Do **not** redesign schemas or domain logic.

---

## Hard Requirements (do not violate)

- No global renames of `super_type`, `btype`, `b_sub_type`
- No live DB migration logic
- No changes to call sites outside DB plumbing
- No behavioral changes beyond name/shape compatibility

---

## Phase 0 — Dependency wiring

**Edit**

- `bloom_env.yaml`
  ```yaml
  -e ../daylily-tapdb
  ```

(Optional)
- `requirements.txt`: add same line

**Check**
```
python -c "import daylily_tapdb"
```

---

## Phase 1 — Create TapDB adapter (NO CALL SITE CHANGES)

**Create** `bloom_lims/tapdb_adapter.py`

### Import

- `daylily_tapdb.models.base.Base`
- `tapdb_core`
- `models.template.*`
- `models.instance.*`
- `models.lineage.*`
- `models.audit.audit_log`

### Field compatibility (MANDATORY)

Add SQLAlchemy `synonym()` mappings:

| BLOOM | TapDB |
|------|------|
| `super_type` | `category` |
| `btype` | `type` |
| `b_sub_type` | `subtype` |

Apply at base class level so subclasses inherit.

### Class compatibility (MANDATORY)

Define aliases:

```python
file_set_template = file_template
file_reference_template = file_template
file_set_instance = file_instance
file_reference_instance = file_instance
file_set_instance_lineage = file_instance_lineage
file_reference_instance_lineage = file_instance_lineage
```

### Implement BLOOMdb3

- Preserve constructor defaults
- Preserve members:
  - `engine`
  - `_Session`
  - `session`
  - `Base`
- Implement:
  - `transaction()`
  - `new_session()`
  - `close()`

Populate `self.Base.classes.*` explicitly in `_register_orm_classes()`.

---

## Phase 2 — Flip BLOOM DB entrypoint

**Rename**

- `bloom_lims/db.py → bloom_lims/db_legacy.py`

**Create new** `bloom_lims/db.py`

Re-export symbols from adapter:

```python
from bloom_lims.tapdb_adapter import (
    BLOOMdb3,
    Base,
    bloom_core,
    generic_template,
    generic_instance,
    generic_instance_lineage,
)
```

Do not change import paths elsewhere.

**Check**
```
python -m compileall bloom_lims
```

---

## Phase 3 — Schema bootstrap switch

**Edit** `bloom_lims/env/install_postgres.sh`

- Apply TapDB schema:
  - `${TAPDB_SCHEMA_SQL:-../daylily-tapdb/schema/tapdb_schema.sql}`
- Apply BLOOM prefix sequences

**Create** `bloom_lims/env/bloom_prefix_sequences.sql`

- For each prefix in BLOOM metadata:
  ```sql
  CREATE SEQUENCE IF NOT EXISTS <lower(prefix)>_instance_seq;
  ```

**Reason**

TapDB EUID generation requires per-prefix sequences; BLOOM’s CASE logic is invalid.

---

## Phase 4 — Seed + docs cleanup

**Edit** `seed_db_containersGeneric.py`

- Remove grep / CASE checks against `postgres_schema_v3.sql`
- Assume sequences exist

**Update references**

- `bloom_lims/migrations/*`
- `README.md`
- `BLOOM_SPECIFICATION.md`

Replace mentions of `postgres_schema_v3.sql` with TapDB schema.

---

## Phase 5 — Enforce single DB source

**Delete**

- `bloom_lims/db_legacy.py`
- `bloom_lims/env/postgres_schema_v3.sql`

**Verify**
```
grep -R "postgres_schema_v3.sql" -n .
```

---

## Validation Ladder (must pass in order)

1. Imports compile
2. DB connects
3. Schema applies
4. Seed runs
5. CLI smoke
6. API smoke

Stop immediately if any step fails.

---

## Non-goals (explicit)

- Redesigning polymorphic inheritance
- Changing EUID formats
- Introducing new abstractions
- Optimizing performance

---

## Done Condition

BLOOM runs end-to-end using TapDB with zero call-site changes and identical runtime behavior.

