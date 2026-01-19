# TAPDB: Templated Abstract Polymorphic Database Library

## Technical Specification Document

**Version:** 1.0.0
**Status:** Draft
**Date:** 2026-01-18

---

## Table of Contents

1. [Library Overview & Architecture](#1-library-overview--architecture)
2. [Database Schema Specification](#2-database-schema-specification)
3. [Object Model & ORM Design](#3-object-model--orm-design)
4. [Template System Specification](#4-template-system-specification)
5. [API Interface Design](#5-api-interface-design)
6. [Configuration & Integration](#6-configuration--integration)
7. [Development Guidelines](#7-development-guidelines)
8. [Repository Structure & Packaging](#8-repository-structure--packaging)

---

## 1. Library Overview & Architecture

### 1.1 Purpose and Design Philosophy

TAPDB (Templated Abstract Polymorphic Database) is a standalone, reusable library that implements a **three-table polymorphic object model** with JSON-driven template configuration. The core innovation is enabling new object types to be defined through JSON templates without requiring code changes or database migrations.

**Design Principles:**

- **Template-Driven:** Object types are defined declaratively in JSON, not code
- **Polymorphic Inheritance:** Single-table inheritance via discriminator columns
- **Lineage Tracking:** First-class support for parent-child relationships between objects
- **Soft Deletes:** All deletes are logical (is_deleted flag), never physical
- **Audit Trail:** Automatic tracking of all changes via database triggers
- **Singleton Support:** Templates can enforce single-instance constraints

### 1.2 Core Concepts

#### Templates vs Instances

| Concept | Description |
|---------|-------------|
| **Template** | A blueprint defining an object type, stored in `generic_template`. Contains JSON schema, default values, instantiation layouts, and action definitions. |
| **Instance** | A concrete object created from a template, stored in `generic_instance`. Inherits structure from template with instance-specific values. |
| **Lineage** | A relationship between two instances (parent-child), stored in `generic_instance_lineage`. |

#### Polymorphic Inheritance

The `polymorphic_discriminator` column enables SQLAlchemy's single-table inheritance pattern:

```
generic_template (base)
├── container_template
├── content_template
├── workflow_template
├── equipment_template
├── actor_template
├── action_template
└── ... (extensible)
```

Each polymorphic subclass shares the same table but is treated as a distinct Python class.

#### JSON-Driven Configuration

All customization happens through the `json_addl` JSONB column:

```json
{
  "properties": { "custom_field": "value" },
  "instantiation_layouts": [ ... ],
  "action_groups": { ... },
  "action_imports": { ... }
}
```

### 1.3 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TAPDB Architecture                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         Application Layer                             │   │
│  │   BloomObj / Domain Classes (Container, Workflow, Equipment, etc.)   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                          ORM Layer (SQLAlchemy)                       │   │
│  │   ┌────────────────┐  ┌─────────────────┐  ┌─────────────────────┐   │   │
│  │   │ bloom_core     │  │ generic_template│  │ generic_instance    │   │   │
│  │   │ (abstract)     │──│ (polymorphic)   │──│ (polymorphic)       │   │   │
│  │   └────────────────┘  └─────────────────┘  └─────────────────────┘   │   │
│  │                                               │                       │   │
│  │                              ┌────────────────┴────────────────┐      │   │
│  │                              │ generic_instance_lineage        │      │   │
│  │                              │ (polymorphic)                   │      │   │
│  │                              └─────────────────────────────────┘      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         PostgreSQL Database                           │   │
│  │   ┌─────────────────┐  ┌────────────────┐  ┌─────────────────────┐   │   │
│  │   │generic_template │  │generic_instance│  │generic_instance_    │   │   │
│  │   │                 │  │                │  │lineage              │   │   │
│  │   ├─────────────────┤  ├────────────────┤  ├─────────────────────┤   │   │
│  │   │+ uuid (PK)      │  │+ uuid (PK)     │  │+ uuid (PK)          │   │   │
│  │   │+ euid (unique)  │  │+ euid (unique) │  │+ euid (unique)      │   │   │
│  │   │+ polymorphic_   │  │+ template_uuid │  │+ parent_instance_   │   │   │
│  │   │  discriminator  │  │+ polymorphic_  │  │  uuid (FK)          │   │   │
│  │   │+ json_addl      │  │  discriminator │  │+ child_instance_    │   │   │
│  │   │+ ...            │  │+ json_addl     │  │  uuid (FK)          │   │   │
│  │   │                 │  │+ ...           │  │+ ...                │   │   │
│  │   └─────────────────┘  └────────────────┘  └─────────────────────┘   │   │
│  │                                                                       │   │
│  │   ┌─────────────────────────────────────────────────────────────┐    │   │
│  │   │                      audit_log                               │    │   │
│  │   │  (automatic change tracking via triggers)                    │    │   │
│  │   └─────────────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema Specification

### 2.1 Core Tables Overview

The TAPDB schema consists of **three operational tables** plus an **audit log table**:

| Table | Purpose | Record Count (typical) |
|-------|---------|----------------------|
| `generic_template` | Blueprint definitions | 10s - 100s |
| `generic_instance` | Concrete objects | 1000s - millions |
| `generic_instance_lineage` | Relationships | 1000s - millions |
| `audit_log` | Change history | Grows continuously |

### 2.2 generic_template Table

Complete DDL for the template table:

```sql
CREATE SEQUENCE generic_template_seq;

CREATE TABLE generic_template (
    -- Primary identification
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE NOT NULL DEFAULT ('GT' || nextval('generic_template_seq')),
    name TEXT NOT NULL,

    -- Type hierarchy
    polymorphic_discriminator TEXT NOT NULL,  -- e.g., 'container_template'
    super_type TEXT NOT NULL,                  -- e.g., 'container'
    btype TEXT NOT NULL,                       -- e.g., 'plate'
    b_sub_type TEXT NOT NULL,                  -- e.g., 'fixed-plate-96'
    version TEXT NOT NULL,                     -- e.g., '1.0'

    -- Instance configuration
    instance_prefix TEXT NOT NULL,             -- EUID prefix for instances, e.g., 'CX'

    -- Flexible data storage
    json_addl JSONB NOT NULL,                  -- Template definition and defaults
    json_addl_schema JSONB,                    -- Optional JSON Schema for validation

    -- Status and lifecycle
    bstatus TEXT NOT NULL,                     -- e.g., 'ready', 'deprecated'
    is_singleton BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Enforce singleton uniqueness (only one template per type+version combo)
CREATE UNIQUE INDEX idx_generic_template_unique_singleton_key
ON generic_template (super_type, btype, b_sub_type, version)
WHERE is_singleton = TRUE;

-- Uniqueness constraint for all templates
ALTER TABLE generic_template
ADD CONSTRAINT unique_super_type_btype_b_sub_type_version
UNIQUE (super_type, btype, b_sub_type, version);

-- Performance indexes
CREATE INDEX idx_generic_template_singleton ON generic_template(is_singleton);
CREATE INDEX idx_generic_template_type ON generic_template(btype);
CREATE INDEX idx_generic_template_euid ON generic_template(euid);
CREATE INDEX idx_generic_template_is_deleted ON generic_template(is_deleted);
CREATE INDEX idx_generic_template_super_type ON generic_template(super_type);
CREATE INDEX idx_generic_template_b_sub_type ON generic_template(b_sub_type);
CREATE INDEX idx_generic_template_version ON generic_template(version);
CREATE INDEX idx_generic_template_mod_dt ON generic_template(modified_dt);
CREATE INDEX idx_generic_template_instance_prefix ON generic_template(instance_prefix);
CREATE INDEX idx_generic_template_polymorphic_discriminator ON generic_template(polymorphic_discriminator);

-- GIN index for JSON queries
CREATE INDEX idx_generic_template_json_addl_gin ON generic_template USING GIN (json_addl);

-- Composite index for common query patterns
CREATE INDEX idx_generic_template_composite
ON generic_template(super_type, btype, b_sub_type, version, is_deleted);
```

### 2.3 generic_instance Table

Complete DDL for the instance table:

```sql
-- Multiple sequences for different EUID prefixes
CREATE SEQUENCE generic_instance_seq;
CREATE SEQUENCE cx_instance_seq;   -- Containers
CREATE SEQUENCE mx_instance_seq;   -- Content/Materials
CREATE SEQUENCE wx_instance_seq;   -- Workflows
CREATE SEQUENCE wsx_instance_seq;  -- Workflow Steps
CREATE SEQUENCE ex_instance_seq;   -- Equipment
CREATE SEQUENCE ax_instance_seq;   -- Actors
CREATE SEQUENCE fx_instance_seq;   -- Files
-- ... additional sequences as needed

CREATE TABLE generic_instance (
    -- Primary identification
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE,  -- Set by trigger based on template's instance_prefix
    name TEXT NOT NULL,

    -- Type hierarchy (copied from template)
    polymorphic_discriminator TEXT NOT NULL,
    super_type TEXT NOT NULL,
    btype TEXT NOT NULL,
    b_sub_type TEXT NOT NULL,
    version TEXT NOT NULL,

    -- Template reference
    template_uuid UUID NOT NULL REFERENCES generic_template(uuid),

    -- Flexible data storage
    json_addl JSONB NOT NULL,

    -- Status and lifecycle
    bstatus TEXT NOT NULL,
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- EUID auto-generation trigger
CREATE OR REPLACE FUNCTION set_generic_instance_euid()
RETURNS TRIGGER AS $$
DECLARE
    prefix TEXT;
    seq_val BIGINT;
BEGIN
    SELECT instance_prefix INTO prefix FROM generic_template WHERE uuid = NEW.template_uuid;

    seq_val := CASE
        WHEN prefix = 'CX' THEN nextval('cx_instance_seq')
        WHEN prefix = 'MX' THEN nextval('mx_instance_seq')
        WHEN prefix = 'WX' THEN nextval('wx_instance_seq')
        WHEN prefix = 'WSX' THEN nextval('wsx_instance_seq')
        WHEN prefix = 'EX' THEN nextval('ex_instance_seq')
        -- Add cases for other prefixes
        ELSE nextval('generic_instance_seq')
    END;

    NEW.euid := prefix || seq_val;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_set_generic_instance_euid
BEFORE INSERT ON generic_instance
FOR EACH ROW EXECUTE FUNCTION set_generic_instance_euid();

-- Singleton uniqueness
CREATE UNIQUE INDEX idx_generic_instance_unique_singleton_key
ON generic_instance (super_type, btype, b_sub_type, version)
WHERE is_singleton = TRUE;

-- Performance indexes
CREATE INDEX idx_generic_instance_polymorphic_discriminator ON generic_instance(polymorphic_discriminator);
CREATE INDEX idx_generic_instance_type ON generic_instance(btype);
CREATE INDEX idx_generic_instance_euid ON generic_instance(euid);
CREATE INDEX idx_generic_instance_is_deleted ON generic_instance(is_deleted);
CREATE INDEX idx_generic_instance_template_uuid ON generic_instance(template_uuid);
CREATE INDEX idx_generic_instance_super_type ON generic_instance(super_type);
CREATE INDEX idx_generic_instance_b_sub_type ON generic_instance(b_sub_type);
CREATE INDEX idx_generic_instance_version ON generic_instance(version);
CREATE INDEX idx_generic_instance_mod_dt ON generic_instance(modified_dt);
CREATE INDEX idx_generic_instance_singleton ON generic_instance(is_singleton);

-- GIN index for JSON queries
CREATE INDEX idx_generic_instance_json_addl_gin ON generic_instance USING GIN (json_addl);
```



### 2.4 generic_instance_lineage Table

Complete DDL for the lineage (relationship) table:

```sql
CREATE SEQUENCE generic_instance_lineage_seq;

CREATE TABLE generic_instance_lineage (
    -- Primary identification
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE NOT NULL DEFAULT ('LX' || nextval('generic_instance_lineage_seq')),
    name TEXT NOT NULL,

    -- Type hierarchy
    polymorphic_discriminator TEXT NOT NULL,
    super_type TEXT NOT NULL DEFAULT 'lineage',
    btype TEXT NOT NULL DEFAULT 'lineage',
    b_sub_type TEXT NOT NULL DEFAULT 'generic',
    version TEXT NOT NULL DEFAULT '1.0',

    -- Relationship definition
    parent_instance_uuid UUID NOT NULL REFERENCES generic_instance(uuid),
    child_instance_uuid UUID NOT NULL REFERENCES generic_instance(uuid),
    lineage_type TEXT NOT NULL DEFAULT 'generic',  -- e.g., 'contains', 'derived_from'

    -- Flexible data storage
    json_addl JSONB NOT NULL DEFAULT '{}',

    -- Status and lifecycle
    bstatus TEXT NOT NULL DEFAULT 'active',
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes
CREATE INDEX idx_generic_instance_lineage_parent ON generic_instance_lineage(parent_instance_uuid);
CREATE INDEX idx_generic_instance_lineage_child ON generic_instance_lineage(child_instance_uuid);
CREATE INDEX idx_generic_instance_lineage_type ON generic_instance_lineage(lineage_type);
CREATE INDEX idx_generic_instance_lineage_is_deleted ON generic_instance_lineage(is_deleted);
CREATE INDEX idx_generic_instance_lineage_euid ON generic_instance_lineage(euid);
CREATE INDEX idx_generic_instance_lineage_polymorphic_discriminator ON generic_instance_lineage(polymorphic_discriminator);

-- Composite index for relationship queries
CREATE INDEX idx_generic_instance_lineage_composite
ON generic_instance_lineage(parent_instance_uuid, child_instance_uuid, is_deleted);
```

### 2.5 audit_log Table

Complete DDL for the audit log:

```sql
CREATE SEQUENCE audit_log_seq;

CREATE TABLE audit_log (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rel_table_name TEXT NOT NULL,
    column_name TEXT,
    rel_table_uuid_fk UUID NOT NULL,
    rel_table_euid_fk TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT,
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operation_type TEXT CHECK (operation_type IN ('INSERT', 'UPDATE', 'DELETE')),
    json_addl JSONB,
    super_type TEXT,
    deleted_record_json JSONB,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE
);

-- Performance indexes
CREATE INDEX idx_audit_log_rel_table_name ON audit_log(rel_table_name);
CREATE INDEX idx_audit_log_rel_table_uuid_fk ON audit_log(rel_table_uuid_fk);
CREATE INDEX idx_audit_log_rel_table_euid_fk ON audit_log(rel_table_euid_fk);
CREATE INDEX idx_audit_log_is_deleted ON audit_log(is_deleted);
CREATE INDEX idx_audit_log_operation_type ON audit_log(operation_type);
CREATE INDEX idx_audit_log_changed_at ON audit_log(changed_at);
CREATE INDEX idx_audit_log_changed_by ON audit_log(changed_by);
CREATE INDEX idx_audit_log_json_addl_gin ON audit_log USING GIN (json_addl);
```

### 2.6 Trigger Functions

#### Soft Delete Trigger

```sql
CREATE OR REPLACE FUNCTION soft_delete_row()
RETURNS TRIGGER AS $$
BEGIN
    -- Instead of deleting, set is_deleted = TRUE
    UPDATE generic_template SET is_deleted = TRUE WHERE uuid = OLD.uuid;
    UPDATE generic_instance SET is_deleted = TRUE WHERE uuid = OLD.uuid;
    UPDATE generic_instance_lineage SET is_deleted = TRUE WHERE uuid = OLD.uuid;
    RETURN NULL;  -- Prevent actual deletion
END;
$$ LANGUAGE plpgsql;
```

#### Audit Triggers

```sql
-- Record UPDATE operations
CREATE OR REPLACE FUNCTION record_update()
RETURNS TRIGGER AS $$
DECLARE
    r RECORD;
    column_name TEXT;
    old_value TEXT;
    new_value TEXT;
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;

    FOR r IN SELECT * FROM json_each_text(row_to_json(NEW)) LOOP
        column_name := r.key;
        new_value := r.value;
        EXECUTE format('SELECT ($1).%I', column_name) USING OLD INTO old_value;

        IF old_value IS DISTINCT FROM new_value THEN
            INSERT INTO audit_log (rel_table_name, column_name, old_value, new_value,
                                   changed_by, rel_table_uuid_fk, rel_table_euid_fk, operation_type)
            VALUES (TG_TABLE_NAME, column_name, old_value, new_value,
                    app_username, NEW.uuid, NEW.euid, TG_OP);
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Record INSERT operations
CREATE OR REPLACE FUNCTION record_insert()
RETURNS TRIGGER AS $$
DECLARE
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;

    INSERT INTO audit_log (rel_table_name, rel_table_uuid_fk, rel_table_euid_fk,
                           changed_by, operation_type)
    VALUES (TG_TABLE_NAME, NEW.uuid, NEW.euid, app_username, 'INSERT');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Auto-update modified_dt
CREATE OR REPLACE FUNCTION update_modified_dt()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_dt = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### 2.7 Session-Based User Tracking

To track which user made changes, set the session variable before operations:

```sql
-- Set current user for audit tracking
SET session.current_username = 'john.doe@example.com';

-- Now perform operations - audit_log will record 'john.doe@example.com' as changed_by
UPDATE generic_instance SET name = 'New Name' WHERE uuid = '...';
```



---

## 3. Object Model & ORM Design

### 3.1 Abstract Base Class: bloom_core

All ORM classes inherit from an abstract base class that defines common columns:

```python
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class bloom_core(Base):
    """Abstract base class for all TAPDB entities."""

    __abstract__ = True

    # Primary identification
    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    euid = Column(Text, unique=True, nullable=True)  # Set by trigger
    name = Column(Text, nullable=False)

    # Type hierarchy
    polymorphic_discriminator = Column(Text, nullable=False)
    super_type = Column(Text, nullable=False)
    btype = Column(Text, nullable=False)
    b_sub_type = Column(Text, nullable=False)
    version = Column(Text, nullable=False)

    # Flexible data storage
    json_addl = Column(JSONB, nullable=False, default=dict)

    # Status and lifecycle
    bstatus = Column(Text, nullable=False, default='ready')
    is_singleton = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_dt = Column(DateTime(timezone=True), server_default=func.now())
    modified_dt = Column(DateTime(timezone=True), onupdate=func.now())
```

### 3.2 Template ORM Classes

```python
class generic_template(bloom_core):
    """Base template class with polymorphic inheritance."""

    __tablename__ = 'generic_template'

    # Additional template-specific columns
    instance_prefix = Column(Text, nullable=False)
    json_addl_schema = Column(JSONB, nullable=True)

    # Polymorphic configuration
    __mapper_args__ = {
        'polymorphic_on': 'polymorphic_discriminator',
        'polymorphic_identity': 'generic_template'
    }


class container_template(generic_template):
    """Template for container objects (plates, tubes, boxes, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'container_template'
    }


class content_template(generic_template):
    """Template for content/material objects (samples, reagents, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'content_template'
    }


class workflow_template(generic_template):
    """Template for workflow objects."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_template'
    }


class equipment_template(generic_template):
    """Template for equipment objects."""

    __mapper_args__ = {
        'polymorphic_identity': 'equipment_template'
    }


class actor_template(generic_template):
    """Template for actor objects (users, organizations, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'actor_template'
    }


class action_template(generic_template):
    """Template for action definitions."""

    __mapper_args__ = {
        'polymorphic_identity': 'action_template'
    }
```

### 3.3 Instance ORM Classes

```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

class generic_instance(bloom_core):
    """Base instance class with polymorphic inheritance."""

    __tablename__ = 'generic_instance'

    # Template reference
    template_uuid = Column(UUID(as_uuid=True), ForeignKey('generic_template.uuid'), nullable=False)

    # Relationships
    template = relationship('generic_template', foreign_keys=[template_uuid])

    # Lineage relationships
    parent_of_lineages = relationship(
        'generic_instance_lineage',
        foreign_keys='generic_instance_lineage.parent_instance_uuid',
        back_populates='parent_instance'
    )
    child_of_lineages = relationship(
        'generic_instance_lineage',
        foreign_keys='generic_instance_lineage.child_instance_uuid',
        back_populates='child_instance'
    )

    __mapper_args__ = {
        'polymorphic_on': 'polymorphic_discriminator',
        'polymorphic_identity': 'generic_instance'
    }


class container_instance(generic_instance):
    """Instance of a container (plate, tube, box, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'container_instance'
    }


class content_instance(generic_instance):
    """Instance of content/material (sample, reagent, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'content_instance'
    }


class workflow_instance(generic_instance):
    """Instance of a workflow."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_instance'
    }


# ... similar pattern for other instance types
```

### 3.4 Lineage ORM Class

```python
class generic_instance_lineage(bloom_core):
    """Tracks parent-child relationships between instances."""

    __tablename__ = 'generic_instance_lineage'

    # Relationship definition
    parent_instance_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey('generic_instance.uuid'),
        nullable=False
    )
    child_instance_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey('generic_instance.uuid'),
        nullable=False
    )
    lineage_type = Column(Text, nullable=False, default='generic')

    # Relationships
    parent_instance = relationship(
        'generic_instance',
        foreign_keys=[parent_instance_uuid],
        back_populates='parent_of_lineages'
    )
    child_instance = relationship(
        'generic_instance',
        foreign_keys=[child_instance_uuid],
        back_populates='child_of_lineages'
    )

    __mapper_args__ = {
        'polymorphic_on': 'polymorphic_discriminator',
        'polymorphic_identity': 'generic_instance_lineage'
    }
```


---

## 4. Template System Specification

### 4.1 Template Code Format

Templates are identified by a **template code string** with the format:

```
{super_type}/{btype}/{b_sub_type}/{version}/
```

**Examples:**
- `container/plate/fixed-plate-96/1.0/`
- `workflow/assay/ngs-library-prep/2.1/`
- `content/sample/blood-specimen/1.0/`
- `equipment/instrument/sequencer/1.0/`

### 4.2 Template JSON Structure

The `json_addl` column contains the complete template definition:

```json
{
  "properties": {
    "custom_field_1": "default_value",
    "custom_field_2": 123,
    "nested_object": {
      "key": "value"
    }
  },
  "instantiation_layouts": [
    {
      "layout_name": "default",
      "layout_string": "content/well/well-96/1.0/",
      "count": 96,
      "naming_pattern": "{parent_name}_{index:02d}",
      "lineage_type": "contains"
    }
  ],
  "action_groups": {
    "primary": ["set_object_status", "print_barcode_label"],
    "secondary": ["add-relationships"]
  },
  "action_imports": {
    "set_object_status": "action/core/set_object_status/1.0/",
    "print_barcode_label": "action/core/print_barcode_label/1.0/",
    "add-relationships": "action/core/add-relationships/1.0/"
  },
  "actions": {
    "custom_action": {
      "action_name": "Custom Action",
      "method_name": "do_action_custom",
      "action_enabled": "1",
      "max_executions": "-1",
      "capture_data": "yes",
      "captured_data": {
        "_field_name": "Label: <input type=\"text\" name=\"field_name\" />"
      }
    }
  },
  "cogs": {
    "unit_cost": 0.50,
    "currency": "USD"
  }
}
```

### 4.3 Instantiation Layouts

Instantiation layouts define child objects to create automatically when an instance is created:

```json
{
  "instantiation_layouts": [
    {
      "layout_name": "wells",
      "layout_string": "container/well/well-96/1.0/",
      "count": 96,
      "naming_pattern": "{parent_name}_W{index:02d}",
      "lineage_type": "contains",
      "properties": {
        "row": "{row_letter}",
        "column": "{column_number}"
      }
    },
    {
      "layout_name": "lid",
      "layout_string": "container/lid/plate-lid/1.0/",
      "count": 1,
      "naming_pattern": "{parent_name}_LID",
      "lineage_type": "covers"
    }
  ]
}
```

**Layout Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `layout_name` | string | Identifier for this layout |
| `layout_string` | string | Template code for child objects |
| `count` | integer | Number of children to create |
| `naming_pattern` | string | Pattern for child names (supports placeholders) |
| `lineage_type` | string | Relationship type (e.g., 'contains', 'derived_from') |
| `properties` | object | Default properties for children |

### 4.4 Action System

Actions are methods that can be executed on instances. They are defined in templates and can be imported from shared action templates.

#### Action Template Structure

```json
{
  "action_name": "Set Status",
  "method_name": "do_action_set_object_status",
  "action_executed": "0",
  "max_executions": "-1",
  "action_enabled": "1",
  "capture_data": "yes",
  "captured_data": {
    "_object_status": "<select name=\"object_status\">...</select>"
  },
  "deactivate_actions_when_executed": [],
  "executed_datetime": [],
  "action_order": "0",
  "action_user": [],
  "description": "Set the status of this object"
}
```

**Action Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `action_name` | string | Display name |
| `method_name` | string | Python method to call |
| `action_enabled` | string | "1" = enabled, "0" = disabled |
| `max_executions` | string | "-1" = unlimited, or positive integer |
| `capture_data` | string | "yes" or "no" |
| `captured_data` | object | HTML form fields for data capture |
| `deactivate_actions_when_executed` | array | Actions to disable after execution |

#### Action Imports

Templates can import actions from shared action templates:

```json
{
  "action_imports": {
    "set_object_status": "action/core/set_object_status/1.0/",
    "print_barcode_label": "action/core/print_barcode_label/1.0/"
  }
}
```

### 4.5 Template Loading

Templates are loaded from JSON files organized by super_type:

```
config/
├── container/
│   ├── metadata.json      # EUID prefix configuration
│   ├── plate.json         # Plate templates
│   ├── tube.json          # Tube templates
│   └── well.json          # Well templates
├── content/
│   ├── metadata.json
│   └── sample.json
├── workflow/
│   ├── metadata.json
│   └── assay.json
├── action/
│   ├── metadata.json
│   └── core.json          # Shared action definitions
└── equipment/
    ├── metadata.json
    └── instrument.json
```

#### metadata.json Format

```json
{
  "euid_prefix": "CX",
  "super_type": "container",
  "description": "Container objects (plates, tubes, wells, etc.)"
}
```


---

## 5. API Interface Design

### 5.1 Database Connection Manager

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Optional
import os

class TAPDBConnection:
    """Database connection manager for TAPDB."""

    def __init__(
        self,
        connection_string: Optional[str] = None,
        echo: bool = False
    ):
        """
        Initialize database connection.

        Args:
            connection_string: PostgreSQL connection string.
                              Falls back to TAPDB_DATABASE_URL env var.
            echo: Enable SQLAlchemy query logging.
        """
        self.connection_string = connection_string or os.environ.get(
            'TAPDB_DATABASE_URL',
            'postgresql://localhost/tapdb'
        )
        self.engine = create_engine(self.connection_string, echo=echo)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._session: Optional[Session] = None

    @property
    def session(self) -> Session:
        """Get or create a session."""
        if self._session is None:
            self._session = self.SessionLocal()
        return self._session

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around operations."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_current_user(self, username: str):
        """Set the current user for audit logging."""
        self.session.execute(
            text(f"SET session.current_username = :username"),
            {"username": username}
        )

    def close(self):
        """Close the current session."""
        if self._session:
            self._session.close()
            self._session = None
```

### 5.2 Template Manager

```python
from pathlib import Path
import json
from typing import Dict, List, Optional, Any

class TemplateManager:
    """Manages template loading and caching."""

    def __init__(self, db: TAPDBConnection, config_path: Path):
        """
        Initialize template manager.

        Args:
            db: Database connection.
            config_path: Path to template configuration directory.
        """
        self.db = db
        self.config_path = config_path
        self._template_cache: Dict[str, generic_template] = {}

    def load_templates_from_config(self) -> int:
        """
        Load all templates from configuration files into database.

        Returns:
            Number of templates loaded.
        """
        count = 0
        for super_type_dir in self.config_path.iterdir():
            if not super_type_dir.is_dir():
                continue

            metadata = self._load_metadata(super_type_dir)
            if not metadata:
                continue

            for template_file in super_type_dir.glob('*.json'):
                if template_file.name == 'metadata.json':
                    continue
                count += self._load_template_file(template_file, metadata)

        return count

    def get_template(self, template_code: str) -> Optional[generic_template]:
        """
        Get a template by its code string.

        Args:
            template_code: Template code (e.g., 'container/plate/fixed-plate-96/1.0/')

        Returns:
            Template object or None if not found.
        """
        if template_code in self._template_cache:
            return self._template_cache[template_code]

        parts = self._parse_template_code(template_code)
        if not parts:
            return None

        template = self.db.session.query(generic_template).filter(
            generic_template.super_type == parts['super_type'],
            generic_template.btype == parts['btype'],
            generic_template.b_sub_type == parts['b_sub_type'],
            generic_template.version == parts['version'],
            generic_template.is_deleted == False
        ).first()

        if template:
            self._template_cache[template_code] = template

        return template

    def _parse_template_code(self, code: str) -> Optional[Dict[str, str]]:
        """Parse a template code string into components."""
        parts = code.strip('/').split('/')
        if len(parts) != 4:
            return None
        return {
            'super_type': parts[0],
            'btype': parts[1],
            'b_sub_type': parts[2],
            'version': parts[3]
        }
```

### 5.3 Instance Factory

```python
class InstanceFactory:
    """Factory for creating instances from templates."""

    def __init__(self, db: TAPDBConnection, template_manager: TemplateManager):
        self.db = db
        self.template_manager = template_manager

    def create_instance(
        self,
        template_code: str,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        create_children: bool = True
    ) -> generic_instance:
        """
        Create an instance from a template.

        Args:
            template_code: Template code string.
            name: Name for the new instance.
            properties: Custom properties to merge with template defaults.
            create_children: Whether to create child objects from instantiation_layouts.

        Returns:
            The created instance.
        """
        template = self.template_manager.get_template(template_code)
        if not template:
            raise ValueError(f"Template not found: {template_code}")

        # Determine instance class based on polymorphic discriminator
        instance_class = self._get_instance_class(template.polymorphic_discriminator)

        # Merge properties with template defaults
        json_addl = dict(template.json_addl)
        if properties:
            json_addl['properties'] = {
                **json_addl.get('properties', {}),
                **properties
            }

        # Create instance
        instance = instance_class(
            name=name,
            template_uuid=template.uuid,
            polymorphic_discriminator=template.polymorphic_discriminator.replace('_template', '_instance'),
            super_type=template.super_type,
            btype=template.btype,
            b_sub_type=template.b_sub_type,
            version=template.version,
            json_addl=json_addl,
            bstatus='ready'
        )

        self.db.session.add(instance)
        self.db.session.flush()  # Get UUID/EUID

        # Create children if requested
        if create_children:
            self._create_children(instance, template)

        return instance

    def _create_children(self, parent: generic_instance, template: generic_template):
        """Create child instances from instantiation_layouts."""
        layouts = template.json_addl.get('instantiation_layouts', [])

        for layout in layouts:
            child_template_code = layout.get('layout_string')
            count = layout.get('count', 1)
            naming_pattern = layout.get('naming_pattern', '{parent_name}_{index}')
            lineage_type = layout.get('lineage_type', 'contains')

            for i in range(count):
                child_name = naming_pattern.format(
                    parent_name=parent.name,
                    index=i + 1
                )

                child = self.create_instance(
                    template_code=child_template_code,
                    name=child_name,
                    properties=layout.get('properties'),
                    create_children=True  # Recursive
                )

                # Create lineage
                self._create_lineage(parent, child, lineage_type)

    def _create_lineage(
        self,
        parent: generic_instance,
        child: generic_instance,
        lineage_type: str
    ) -> generic_instance_lineage:
        """Create a lineage relationship between instances."""
        lineage = generic_instance_lineage(
            name=f"{parent.euid}->{child.euid}",
            parent_instance_uuid=parent.uuid,
            child_instance_uuid=child.uuid,
            lineage_type=lineage_type,
            polymorphic_discriminator='generic_instance_lineage',
            super_type='lineage',
            btype='lineage',
            b_sub_type=lineage_type,
            version='1.0',
            bstatus='active'
        )
        self.db.session.add(lineage)
        return lineage
```


---

## 6. Configuration & Integration

### 6.1 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TAPDB_DATABASE_URL` | PostgreSQL connection string | `postgresql://localhost/tapdb` |
| `TAPDB_CONFIG_PATH` | Path to template configuration | `./config` |
| `TAPDB_ECHO_SQL` | Enable SQL query logging | `false` |
| `TAPDB_POOL_SIZE` | Connection pool size | `5` |
| `TAPDB_MAX_OVERFLOW` | Max overflow connections | `10` |

### 6.2 Integration Patterns

#### As a Python Package Dependency

```python
# In your application
from tapdb import TAPDBConnection, TemplateManager, InstanceFactory
from tapdb.models import generic_instance, container_instance

# Initialize
db = TAPDBConnection(os.environ['DATABASE_URL'])
templates = TemplateManager(db, Path('./config'))
factory = InstanceFactory(db, templates)

# Create objects
plate = factory.create_instance(
    template_code='container/plate/fixed-plate-96/1.0/',
    name='PLATE-001'
)
db.session.commit()
```

#### Extending with Custom Types

```python
from tapdb.models import generic_instance, generic_template

class my_custom_instance(generic_instance):
    """Custom instance type for domain-specific objects."""

    __mapper_args__ = {
        'polymorphic_identity': 'my_custom_instance'
    }

    def custom_method(self):
        """Domain-specific behavior."""
        pass
```

#### Custom Action Handlers

```python
class CustomActionHandler:
    """Handler for custom actions."""

    def __init__(self, db: TAPDBConnection):
        self.db = db

    def do_action_custom(self, instance: generic_instance, data: dict) -> dict:
        """
        Execute a custom action.

        Args:
            instance: The instance to act on.
            data: Captured data from the action form.

        Returns:
            Result dictionary with status and message.
        """
        # Implement custom logic
        instance.json_addl['properties']['custom_field'] = data.get('value')
        flag_modified(instance, 'json_addl')

        return {'status': 'success', 'message': 'Action completed'}
```

### 6.3 Database Migration Strategy

#### Initial Setup

```bash
# Create database
createdb tapdb

# Apply schema
psql tapdb < schema/tapdb_schema.sql

# Load initial templates
python -m tapdb.cli load-templates --config ./config
```

#### Schema Versioning

Use a migration tool like Alembic for schema changes:

```python
# alembic/versions/001_initial.py
def upgrade():
    # Schema is managed via raw SQL for trigger support
    op.execute(open('schema/tapdb_schema.sql').read())

def downgrade():
    op.drop_table('audit_log')
    op.drop_table('generic_instance_lineage')
    op.drop_table('generic_instance')
    op.drop_table('generic_template')
```

### 6.4 Performance Considerations

#### JSON Query Optimization

Use GIN indexes for efficient JSONB queries:

```sql
-- Query properties efficiently
SELECT * FROM generic_instance
WHERE json_addl->'properties'->>'sample_type' = 'blood';

-- Use containment operator with GIN index
SELECT * FROM generic_instance
WHERE json_addl @> '{"properties": {"sample_type": "blood"}}';
```

#### Batch Operations

```python
def create_instances_batch(
    factory: InstanceFactory,
    template_code: str,
    names: List[str],
    batch_size: int = 100
) -> List[generic_instance]:
    """Create multiple instances efficiently."""
    instances = []

    for i in range(0, len(names), batch_size):
        batch_names = names[i:i + batch_size]

        for name in batch_names:
            instance = factory.create_instance(
                template_code=template_code,
                name=name,
                create_children=False  # Create children separately
            )
            instances.append(instance)

        factory.db.session.flush()

    return instances
```


---

## 7. Development Guidelines

See [AGENT.md](./AGENT.md) for detailed development guidelines and AI assistant instructions.

### 7.1 Code Style

- Follow PEP 8 for Python code
- Use type hints for all function signatures
- Document all public APIs with docstrings
- Use `black` for formatting, `ruff` for linting

### 7.2 Testing Requirements

- Unit tests for all ORM models
- Integration tests for database operations
- Test coverage minimum: 80%
- Use pytest with fixtures for database setup

### 7.3 Commit Conventions

```
<type>(<scope>): <description>

Types: feat, fix, docs, style, refactor, test, chore
Scopes: models, schema, api, templates, cli
```

---

## 8. Repository Structure & Packaging

### 8.1 Recommended Repository Structure

```
tapdb/
├── README.md                    # Quick start and overview
├── SPECIFICATION.md             # This document
├── AGENT.md                     # AI assistant guidelines
├── LICENSE                      # MIT License
├── pyproject.toml               # Package configuration
├── setup.py                     # Legacy setup (if needed)
│
├── tapdb/                       # Main package
│   ├── __init__.py              # Package exports
│   ├── _version.py              # Version info
│   ├── connection.py            # TAPDBConnection class
│   ├── models/                  # ORM models
│   │   ├── __init__.py
│   │   ├── base.py              # bloom_core abstract class
│   │   ├── template.py          # Template classes
│   │   ├── instance.py          # Instance classes
│   │   └── lineage.py           # Lineage class
│   ├── templates/               # Template management
│   │   ├── __init__.py
│   │   ├── manager.py           # TemplateManager
│   │   ├── loader.py            # JSON file loading
│   │   └── parser.py            # Template code parsing
│   ├── factory/                 # Instance creation
│   │   ├── __init__.py
│   │   └── instance.py          # InstanceFactory
│   ├── actions/                 # Action system
│   │   ├── __init__.py
│   │   ├── handler.py           # Action execution
│   │   └── registry.py          # Action registration
│   └── cli/                     # Command-line interface
│       ├── __init__.py
│       └── main.py
│
├── schema/                      # Database schema
│   ├── tapdb_schema.sql         # Complete DDL
│   └── migrations/              # Alembic migrations
│
├── config/                      # Default templates
│   ├── container/
│   ├── content/
│   ├── workflow/
│   └── action/
│
├── tests/                       # Test suite
│   ├── conftest.py              # Pytest fixtures
│   ├── test_models.py
│   ├── test_templates.py
│   ├── test_factory.py
│   └── test_integration.py
│
├── docs/                        # Documentation
│   ├── api/                     # API reference
│   └── examples/                # Usage examples
│
└── examples/                    # Example applications
    ├── simple_lims/
    └── inventory_tracker/
```

### 8.2 Package Configuration (pyproject.toml)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "tapdb"
version = "1.0.0"
description = "Templated Abstract Polymorphic Database - A flexible object model library"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.10"
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Database",
    "Topic :: Software Development :: Libraries",
]
keywords = ["database", "orm", "polymorphic", "templates", "sqlalchemy"]

dependencies = [
    "sqlalchemy>=2.0",
    "psycopg2-binary>=2.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "black>=23.0",
    "ruff>=0.1",
    "mypy>=1.0",
]

[project.scripts]
tapdb = "tapdb.cli:main"

[project.urls]
Homepage = "https://github.com/your-org/tapdb"
Repository = "https://github.com/your-org/tapdb.git"
Documentation = "https://tapdb.readthedocs.io"

[tool.setuptools.packages.find]
where = ["."]
include = ["tapdb*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --cov=tapdb"

[tool.black]
line-length = 88
target-version = ['py310', 'py311', 'py312']

[tool.ruff]
line-length = 88
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true
```

### 8.3 Package Exports (__init__.py)

```python
"""
TAPDB: Templated Abstract Polymorphic Database

A flexible, template-driven object model library for Python applications.
"""

from tapdb._version import __version__
from tapdb.connection import TAPDBConnection
from tapdb.models import (
    bloom_core,
    generic_template,
    generic_instance,
    generic_instance_lineage,
    container_template,
    container_instance,
    content_template,
    content_instance,
    workflow_template,
    workflow_instance,
)
from tapdb.templates import TemplateManager
from tapdb.factory import InstanceFactory

__all__ = [
    "__version__",
    "TAPDBConnection",
    "TemplateManager",
    "InstanceFactory",
    "bloom_core",
    "generic_template",
    "generic_instance",
    "generic_instance_lineage",
    "container_template",
    "container_instance",
    "content_template",
    "content_instance",
    "workflow_template",
    "workflow_instance",
]
```

---

## Appendix A: EUID Prefix Registry

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `GT` | template | Generic templates |
| `CX` | container | Containers (plates, tubes, boxes) |
| `MX` | content | Materials/content (samples, reagents) |
| `WX` | workflow | Workflows |
| `WSX` | workflow_step | Workflow steps |
| `EX` | equipment | Equipment/instruments |
| `AX` | actor | Actors (users, organizations) |
| `FX` | file | File references |
| `LX` | lineage | Lineage relationships |

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **EUID** | Enterprise Unique Identifier - human-readable ID with type prefix |
| **Template** | Blueprint defining an object type's structure and behavior |
| **Instance** | Concrete object created from a template |
| **Lineage** | Parent-child relationship between instances |
| **Polymorphic Discriminator** | Column value determining the Python class for a row |
| **Instantiation Layout** | Definition of child objects to create automatically |
| **Action** | Executable method defined in a template |
| **json_addl** | JSONB column storing flexible, schema-free data |

---

*Document generated for TAPDB Library Extraction from BLOOM LIMS*
