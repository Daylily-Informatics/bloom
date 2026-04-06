# daylily-tapdb Development Rules

## Core Invariants

These rules must NEVER be violated. They are fundamental to the daylily-tapdb architecture.

### Rule 1: Three-Table Model

**NEVER add new database tables for new object types.**

All objects must be stored in one of:
- `generic_template` - for blueprints/definitions
- `generic_instance` - for concrete objects
- `generic_instance_lineage` - for relationships

New object types are defined via JSON templates and polymorphic discriminators.

### Rule 2: Soft Deletes Only

**NEVER use physical DELETE operations.**

Always set `is_deleted = TRUE` instead:

```python
# Correct
instance.is_deleted = True
session.commit()

# WRONG - never do this
session.delete(instance)
```

### Rule 3: Audit Trail Integrity

**ALWAYS set session.current_username before database operations.**

```python
db.set_current_user('user@example.com')
# Now perform operations
```

### Rule 4: JSON Modification Pattern

**ALWAYS use flag_modified after modifying json_addl.**

```python
from sqlalchemy.orm.attributes import flag_modified

instance.json_addl['properties']['key'] = 'value'
flag_modified(instance, 'json_addl')  # Required!
```

### Rule 5: Template Code Format

**ALWAYS use the standard template code format with trailing slash.**

```
{category}/{type}/{subtype}/{version}/
```

Example: `container/plate/fixed-plate-96/1.0/`

> **Note:** Field names were updated to align with TapDB conventions:
> - `super_type` → `category`
> - `btype` → `type`
> - `b_sub_type` → `subtype`

### Rule 6: Polymorphic Identity Naming

**Polymorphic identities must follow the naming convention:**

- Templates: `{category}_template` (e.g., `container_template`)
- Instances: `{category}_instance` (e.g., `container_instance`)

### Rule 7: EUID Immutability

**NEVER modify an EUID after creation.**

EUIDs are set by database triggers and must remain constant for the object's lifetime.

### Rule 8: Transaction Boundaries

**Library code must NOT commit transactions.**

Let the caller manage transaction boundaries:

```python
# In library code - correct
def create_instance(...):
    instance = ...
    session.add(instance)
    session.flush()  # OK - gets IDs without committing
    return instance

# In library code - WRONG
def create_instance(...):
    instance = ...
    session.add(instance)
    session.commit()  # NO - caller should control this
    return instance
```

### Rule 9: Lineage Acyclicity

**NEVER create circular lineage relationships.**

Before creating lineage, verify no cycle would be created:

```python
def would_create_cycle(parent_uuid, child_uuid, session):
    """Check if making parent->child would create a cycle."""
    # Walk up from parent to see if we reach child
    ...
```

### Rule 10: Template Singleton Enforcement

**Respect is_singleton constraints.**

When `is_singleton = TRUE`, only one template can exist for a given (category, type, subtype, version) combination.

---

## Code Quality Rules

### Rule 11: Type Hints Required

All public functions must have type hints:

```python
def create_instance(
    template_code: str,
    name: str,
    properties: Optional[Dict[str, Any]] = None
) -> generic_instance:
    ...
```

### Rule 12: Docstrings Required

All public APIs must have docstrings:

```python
def create_instance(template_code: str, name: str) -> generic_instance:
    """
    Create an instance from a template.
    
    Args:
        template_code: Template code string (e.g., 'container/plate/fixed-plate-96/1.0/')
        name: Name for the new instance.
    
    Returns:
        The created instance.
    
    Raises:
        TemplateNotFoundError: If template_code doesn't resolve.
    """
```

### Rule 13: Test Coverage

- Minimum 80% overall coverage
- 95%+ for critical paths (instance creation, lineage, template loading)
- All bug fixes must include regression tests

### Rule 14: Error Context

Error messages must include actionable context:

```python
# Good
raise TemplateNotFoundError(
    f"Template not found: {template_code}. "
    f"Available templates: {available}"
)

# Bad
raise TemplateNotFoundError("Not found")
```

---

## Performance Rules

### Rule 15: Batch Large Operations

Operations on >100 items must be batched:

```python
BATCH_SIZE = 100
for i in range(0, len(items), BATCH_SIZE):
    batch = items[i:i + BATCH_SIZE]
    process_batch(batch)
    session.flush()
```

### Rule 16: Use GIN-Indexed JSON Queries

Prefer containment operators for JSON queries:

```python
# Good - uses GIN index
.filter(instance.json_addl.contains({'properties': {'type': 'x'}}))

# Avoid - less efficient
.filter(instance.json_addl['properties']['type'].astext == 'x')
```

---

*daylily-tapdb Development Rules - Enforce via code review and CI checks*
