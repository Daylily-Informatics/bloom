# daylily-tapdb Development Guidelines (AGENT.md)

## AI Assistant Instructions

This document provides guidelines for AI assistants working on the **daylily-tapdb** (Templated Abstract Polymorphic Database) library.

**Repository:** `github.com/Daylily-Informatics/daylily-tapdb`
**Package:** `daylily_tapdb` (underscore for Python imports)

---

## Project Overview

daylily-tapdb is a standalone library extracted from BLOOM LIMS that implements a **three-table polymorphic object model** with JSON-driven template configuration. The core innovation is enabling new object types through JSON templates without code changes.

### Key Files

| File/Directory | Purpose |
|----------------|---------|
| `daylily_tapdb/models/` | SQLAlchemy ORM classes |
| `daylily_tapdb/connection.py` | Database connection manager |
| `daylily_tapdb/templates/` | Template loading and management |
| `daylily_tapdb/factory/` | Instance creation logic |
| `daylily_tapdb/actions/` | Action dispatcher (abstract base) |
| `daylily_tapdb/euid.py` | EUID configuration |
| `schema/tapdb_schema.sql` | PostgreSQL DDL |

---

## Architecture Principles

### 1. Three-Table Model

All data lives in three tables:
- `generic_template` - Blueprints/definitions
- `generic_instance` - Concrete objects
- `generic_instance_lineage` - Relationships

**Never add new tables for new object types.** New types are defined via JSON templates.

### 2. Polymorphic Inheritance

Use SQLAlchemy's single-table inheritance:

```python
class container_instance(generic_instance):
    __mapper_args__ = {
        'polymorphic_identity': 'container_instance'
    }
```

### 3. JSON-Driven Configuration

All customization happens in `json_addl`:
- Properties
- Instantiation layouts
- Actions
- Metadata

### 4. Soft Deletes

**Never use DELETE.** Always set `is_deleted = TRUE`.

### 5. Audit Trail

All changes are tracked via database triggers. Set `session.current_username` before operations.

---

## Coding Standards

### Python Style

- Python 3.10+ required
- Type hints on all public functions
- Docstrings for all public APIs
- Format with `black`, lint with `ruff`

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| ORM classes | snake_case | `generic_instance` |
| Python classes | PascalCase | `TemplateManager` |
| Functions | snake_case | `create_instance` |
| Constants | UPPER_SNAKE | `DEFAULT_BATCH_SIZE` |
| Template codes | slash-separated | `container/plate/fixed-plate-96/1.0/` |

### Import Order

```python
# Standard library
import os
from pathlib import Path

# Third-party
from sqlalchemy import Column, Text
from sqlalchemy.orm import relationship

# Local
from daylily_tapdb.models import generic_instance
from daylily_tapdb.connection import TAPDBConnection
```

---

## Database Guidelines

### Schema Changes

1. **Never modify core table structure** without migration
2. Use Alembic for all schema changes
3. Test migrations both up and down
4. Preserve trigger functions

### JSON Queries

Use GIN-indexed patterns:

```python
# Good - uses GIN index
session.query(generic_instance).filter(
    generic_instance.json_addl.contains({'properties': {'type': 'blood'}})
)

# Avoid - doesn't use index efficiently
session.query(generic_instance).filter(
    generic_instance.json_addl['properties']['type'].astext == 'blood'
)
```

### Session Management

```python
# Always use context manager for transactions
with db.session_scope() as session:
    instance = factory.create_instance(...)
    # Auto-commits on success, rolls back on exception
```

---

## Template System

### Template Code Format

```
{super_type}/{btype}/{b_sub_type}/{version}/
```

Always include trailing slash.


---

## Common Tasks

### Adding a New Polymorphic Type

1. Add ORM class in `daylily_tapdb/models/`:

```python
class new_type_instance(generic_instance):
    __mapper_args__ = {
        'polymorphic_identity': 'new_type_instance'
    }
```

2. Add template class if needed:

```python
class new_type_template(generic_template):
    __mapper_args__ = {
        'polymorphic_identity': 'new_type_template'
    }
```

3. Register in `__init__.py` exports
4. Add EUID sequence in schema if new prefix needed
5. Register prefix in `EUIDConfig`

### Adding a New Action (Application-Level)

**Note:** daylily-tapdb provides only the abstract `ActionDispatcher`. Concrete actions are implemented in your application.

1. Extend `ActionDispatcher` in your application:

```python
from daylily_tapdb import ActionDispatcher

class MyActionHandler(ActionDispatcher):
    def do_action_new_action(self, instance, action_ds, captured_data):
        # Implementation
        return {'status': 'success', 'message': 'Done'}
```

2. Define action template in your config:

```json
{
  "action_groups": {
    "my_actions": {
      "new_action": {
        "action_name": "New Action",
        "method_name": "do_action_new_action",
        "action_enabled": "1"
      }
    }
  }
}
```

3. Import in target templates via `action_imports`

### Querying Lineage

```python
# Get all children of an instance
children = session.query(generic_instance).join(
    generic_instance_lineage,
    generic_instance_lineage.child_instance_uuid == generic_instance.uuid
).filter(
    generic_instance_lineage.parent_instance_uuid == parent.uuid,
    generic_instance_lineage.is_deleted == False
).all()

# Get all parents
parents = session.query(generic_instance).join(
    generic_instance_lineage,
    generic_instance_lineage.parent_instance_uuid == generic_instance.uuid
).filter(
    generic_instance_lineage.child_instance_uuid == child.uuid,
    generic_instance_lineage.is_deleted == False
).all()
```

---

## Performance Guidelines

### Batch Operations

Always batch large operations:

```python
BATCH_SIZE = 100

for i in range(0, len(items), BATCH_SIZE):
    batch = items[i:i + BATCH_SIZE]
    for item in batch:
        session.add(item)
    session.flush()
```

### Eager Loading

Use `joinedload` for known relationships:

```python
from sqlalchemy.orm import joinedload

instances = session.query(generic_instance).options(
    joinedload(generic_instance.template)
).filter(...).all()
```

### JSON Field Updates

Always use `flag_modified` after updating json_addl:

```python
from sqlalchemy.orm.attributes import flag_modified

instance.json_addl['properties']['key'] = 'value'
flag_modified(instance, 'json_addl')
```

---

## Error Handling

### Standard Exceptions

```python
class TAPDBError(Exception):
    """Base exception for TAPDB."""
    pass

class TemplateNotFoundError(TAPDBError):
    """Raised when a template code doesn't resolve."""
    pass

class InvalidTemplateCodeError(TAPDBError):
    """Raised when template code format is invalid."""
    pass

class LineageError(TAPDBError):
    """Raised for lineage-related errors."""
    pass
```

### Error Messages

Include context in error messages:

```python
raise TemplateNotFoundError(
    f"Template not found: {template_code}. "
    f"Searched in super_type={parts['super_type']}, btype={parts['btype']}"
)
```

---

## Security Considerations

### SQL Injection

Always use parameterized queries:

```python
# Good
session.execute(text("SELECT * FROM t WHERE id = :id"), {"id": user_input})

# Bad - never do this
session.execute(text(f"SELECT * FROM t WHERE id = {user_input}"))
```

### JSON Validation

Validate JSON input before storing:

```python
import jsonschema

def validate_properties(properties: dict, schema: dict):
    jsonschema.validate(properties, schema)
```

---

## Debugging Tips

### Enable SQL Logging

```python
db = TAPDBConnection(echo=True)  # Logs all SQL
```

### Inspect Polymorphic Type

```python
print(instance.polymorphic_discriminator)
print(type(instance).__name__)
```

### Check Audit Trail

```sql
SELECT * FROM audit_log
WHERE rel_table_uuid_fk = 'instance-uuid'
ORDER BY changed_at DESC;
```

---

## Do Not

- ❌ Add new tables for new object types
- ❌ Use physical DELETE operations
- ❌ Modify json_addl without flag_modified
- ❌ Skip audit logging (always set session.current_username)
- ❌ Create circular lineage relationships
- ❌ Use raw SQL without parameterization
- ❌ Commit in library code (let caller manage transactions)

---

## Do

- ✅ Define new types via JSON templates
- ✅ Use soft deletes (is_deleted = TRUE)
- ✅ Use flag_modified for JSON updates
- ✅ Set session.current_username for audit
- ✅ Use batch operations for bulk inserts
- ✅ Write tests for all new functionality
- ✅ Use type hints and docstrings

---

## Library Scope Reminder

**daylily-tapdb includes:**
- 3-table schema (template, instance, lineage) + audit
- ORM layer (`tapdb_core`, all `generic_*` classes)
- Template loader and manager
- Instance factory
- Lineage management
- EUID system (mandatory, prefix-configurable)
- Action dispatcher (abstract base only)
- Workflow types (polymorphic classes only)

**daylily-tapdb does NOT include:**
- Concrete action implementations (`do_action_*` methods)
- Workflow execution logic
- File/S3 storage
- External integrations (printers, tracking, auth)
- Web UI components
- Domain-specific templates

---

*AGENT.md for daylily-tapdb Library - AI Assistant Development Guidelines*
