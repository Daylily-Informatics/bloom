# daylily-tapdb: Templated Abstract Polymorphic Database Library

## Technical Specification Document

**Version:** 1.0.0
**Status:** Draft
**Date:** 2026-01-19
**Repository:** `github.com/Daylily-Informatics/daylily-tapdb`

---

## Table of Contents

1. [Library Overview & Architecture](#1-library-overview--architecture)
2. [Database Schema Specification](#2-database-schema-specification)
3. [Object Model & ORM Design](#3-object-model--orm-design)
4. [Template System Specification](#4-template-system-specification)
5. [API Interface Design](#5-api-interface-design)
6. [Action System](#6-action-system)
7. [Workflow System](#7-workflow-system)
8. [EUID System](#8-euid-system)
9. [Configuration & Integration](#9-configuration--integration)
10. [Development Guidelines](#10-development-guidelines)
11. [Repository Structure & Packaging](#11-repository-structure--packaging)

---

## 1. Library Overview & Architecture

### 1.1 Purpose and Design Philosophy

**daylily-tapdb** (Templated Abstract Polymorphic Database) is a standalone, reusable library that implements a **three-table polymorphic object model** with JSON-driven template configuration. The core innovation is enabling new object types to be defined through JSON templates without requiring code changes or database migrations.

This library is extracted from [BLOOM LIMS](https://github.com/Daylily-Informatics/bloom) to provide the foundational database architecture as a reusable dependency for laboratory, scientific, and general data management applications.

**Design Principles:**

- **Template-Driven:** Object types are defined declaratively in JSON, not code
- **Polymorphic Inheritance:** Single-table inheritance via discriminator columns
- **Lineage Tracking:** First-class support for parent-child relationships between objects
- **Soft Deletes:** All deletes are logical (is_deleted flag), never physical
- **Audit Trail:** Automatic tracking of all changes via database triggers
- **Singleton Support:** Templates can enforce single-instance constraints
- **EUID System:** Human-readable, type-prefixed identifiers (mandatory, prefix-configurable)

### 1.2 Library Scope

#### Included in daylily-tapdb

| Component | Description |
|-----------|-------------|
| **3-Table Schema** | `generic_template`, `generic_instance`, `generic_instance_lineage` + audit |
| **ORM Layer** | `tapdb_core` abstract base, all `generic_*` classes |
| **Polymorphic Types** | Base polymorphic classes for template/instance/lineage |
| **Template Loader** | JSON file → database template records |
| **Lineage Management** | Create/query parent-child relationships |
| **Instantiation Layouts** | Automatic child object creation from templates |
| **EUID System** | Mandatory; core prefixes (GT, GX, GL) always included |
| **Action Dispatcher** | Abstract base class + routing mechanism |
| **Action Instances** | First-class audit/scheduling records (XX prefix) |
| **Workflow Types** | Polymorphic classes for workflow/workflow_step (optional) |
| **Audit Triggers** | Session-based username tracking |

#### EUID Prefix Tiers

| Tier | Prefixes | Description |
|------|----------|-------------|
| **Core** | GT, GX, GL | Always included; required for 3-table model |
| **Optional** | WX, WSX, XX | Library features (workflows, actions) |
| **Application** | CX, MX, EX, ... | User-defined domain prefixes |

#### Excluded (Application-Specific)

| Component | Reason |
|-----------|--------|
| **Concrete Action Implementations** | Domain-specific (e.g., `do_action_print_barcode_label`) |
| **Workflow Execution Logic** | Application-specific queue/state management |
| **Action Scheduler** | Application-specific job execution |
| **File/S3 Storage** | Storage layer is application concern |
| **External Integrations** | zebra_day, FedEx tracking, Supabase auth |
| **Web UI Components** | Cytoscape visualization, HTML form rendering |
| **Domain Templates** | Specific JSON templates (plates, samples, etc.)
| **Domain EUID Prefixes** | Application configures CX, MX, EX, etc.

### 1.3 Core Concepts

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

### 1.4 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       daylily-tapdb Architecture                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    Application Layer (YOUR CODE)                    │    │
│  │   BLOOM / Custom Domain Classes / Action Implementations            │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼                                        │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                     daylily-tapdb Library                           │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │                    ORM Layer (SQLAlchemy)                     │  │    │
│  │  │  ┌──────────────┐  ┌───────────────┐  ┌───────────────────┐  │  │    │
│  │  │  │ tapdb_core   │  │generic_template│ │ generic_instance  │  │  │    │
│  │  │  │ (abstract)   │──│ (polymorphic) │──│ (polymorphic)     │  │  │    │
│  │  │  └──────────────┘  └───────────────┘  └───────────────────┘  │  │    │
│  │  │                                            │                  │  │    │
│  │  │                          ┌─────────────────┴───────────────┐  │  │    │
│  │  │                          │ generic_instance_lineage        │  │  │    │
│  │  │                          │ (polymorphic)                   │  │  │    │
│  │  │                          └─────────────────────────────────┘  │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐  │    │
│  │  │TemplateManager │  │InstanceFactory │  │ ActionDispatcher     │  │    │
│  │  │                │  │                │  │ (abstract base)      │  │    │
│  │  └────────────────┘  └────────────────┘  └──────────────────────┘  │    │
│  │  ┌────────────────────────────────────────────────────────────────┐│    │
│  │  │ EUID System (mandatory, prefix-configurable)                   ││    │
│  │  └────────────────────────────────────────────────────────────────┘│    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼                                        │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                       PostgreSQL Database                           │    │
│  │  ┌───────────────┐  ┌────────────────┐  ┌───────────────────────┐  │    │
│  │  │generic_template│ │generic_instance│  │generic_instance_      │  │    │
│  │  │               │  │                │  │lineage                │  │    │
│  │  ├───────────────┤  ├────────────────┤  ├───────────────────────┤  │    │
│  │  │+ uuid (PK)    │  │+ uuid (PK)     │  │+ uuid (PK)            │  │    │
│  │  │+ euid (unique)│  │+ euid (unique) │  │+ euid (unique)        │  │    │
│  │  │+ polymorphic_ │  │+ template_uuid │  │+ parent_instance_uuid │  │    │
│  │  │  discriminator│  │+ polymorphic_  │  │+ child_instance_uuid  │  │    │
│  │  │+ json_addl    │  │  discriminator │  │+ lineage_type         │  │    │
│  │  │+ ...          │  │+ json_addl     │  │+ ...                  │  │    │
│  │  └───────────────┘  └────────────────┘  └───────────────────────┘  │    │
│  │                                                                     │    │
│  │  ┌───────────────────────────────────────────────────────────────┐ │    │
│  │  │ audit_log (automatic change tracking via triggers)            │ │    │
│  │  └───────────────────────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema Specification

### 2.1 Core Tables Overview

The daylily-tapdb schema consists of **three operational tables** plus an **audit log table**:

| Table | Purpose | Record Count (typical) |
|-------|---------|----------------------|
| `generic_template` | Blueprint definitions | 10s - 100s |
| `generic_instance` | Concrete objects | 1000s - millions |
| `generic_instance_lineage` | Relationships | 1000s - millions |
| `audit_log` | Change history | Grows continuously |

### 2.1.1 Required Extensions

```sql
-- Required for UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

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
    is_singleton BOOLEAN NOT NULL DEFAULT TRUE,  -- ORM consistency; see json_addl.singleton for behavior
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Uniqueness constraint for templates (one template per type+version combo)
-- Note: Partial index on is_singleton removed - the full constraint is sufficient
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
    name TEXT NOT NULL,  -- App-friendly display name (not unique, user-controlled)

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

-- EUID auto-generation trigger (dynamic sequence resolution for extensibility)
CREATE OR REPLACE FUNCTION set_generic_instance_euid()
RETURNS TRIGGER AS $$
DECLARE
    prefix TEXT;
    seq_val BIGINT;
    seq_name TEXT;
BEGIN
    -- Get prefix from template
    SELECT instance_prefix INTO prefix FROM generic_template WHERE uuid = NEW.template_uuid;

    -- Default prefix if template not found or no prefix set
    IF prefix IS NULL THEN
        prefix := 'GX';
    END IF;

    -- Dynamic sequence resolution (allows new prefixes without trigger changes)
    seq_name := lower(prefix) || '_instance_seq';

    BEGIN
        -- Try to use prefix-specific sequence
        EXECUTE format('SELECT nextval(%L)', seq_name) INTO seq_val;
    EXCEPTION WHEN undefined_table THEN
        -- Fallback to generic sequence if prefix sequence doesn't exist
        seq_val := nextval('generic_instance_seq');
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
    euid TEXT UNIQUE NOT NULL DEFAULT ('GL' || nextval('generic_instance_lineage_seq')),
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

Intercepts DELETE operations and converts them to soft deletes with audit logging:

```sql
CREATE OR REPLACE FUNCTION soft_delete_row()
RETURNS TRIGGER AS $$
DECLARE
    app_username TEXT;
BEGIN
    -- Get current user for audit
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;

    -- Soft delete only the row in the triggering table (dynamic SQL)
    EXECUTE format('UPDATE %I SET is_deleted = TRUE WHERE uuid = $1', TG_TABLE_NAME)
    USING OLD.uuid;

    -- Record deletion in audit log with full record snapshot
    INSERT INTO audit_log (
        rel_table_name, rel_table_uuid_fk, rel_table_euid_fk,
        changed_by, operation_type, old_value
    ) VALUES (
        TG_TABLE_NAME, OLD.uuid, OLD.euid,
        app_username, 'DELETE', row_to_json(OLD)::TEXT
    );

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

### 2.6.1 Trigger Attachment

Attach triggers to all three operational tables:

```sql
-- Soft delete triggers (BEFORE DELETE)
CREATE TRIGGER soft_delete_generic_template
    BEFORE DELETE ON generic_template
    FOR EACH ROW EXECUTE FUNCTION soft_delete_row();

CREATE TRIGGER soft_delete_generic_instance
    BEFORE DELETE ON generic_instance
    FOR EACH ROW EXECUTE FUNCTION soft_delete_row();

CREATE TRIGGER soft_delete_generic_instance_lineage
    BEFORE DELETE ON generic_instance_lineage
    FOR EACH ROW EXECUTE FUNCTION soft_delete_row();

-- Audit triggers (AFTER INSERT/UPDATE)
CREATE TRIGGER audit_insert_generic_template
    AFTER INSERT ON generic_template
    FOR EACH ROW EXECUTE FUNCTION record_insert();

CREATE TRIGGER audit_update_generic_template
    AFTER UPDATE ON generic_template
    FOR EACH ROW EXECUTE FUNCTION record_update();

CREATE TRIGGER audit_insert_generic_instance
    AFTER INSERT ON generic_instance
    FOR EACH ROW EXECUTE FUNCTION record_insert();

CREATE TRIGGER audit_update_generic_instance
    AFTER UPDATE ON generic_instance
    FOR EACH ROW EXECUTE FUNCTION record_update();

CREATE TRIGGER audit_insert_generic_instance_lineage
    AFTER INSERT ON generic_instance_lineage
    FOR EACH ROW EXECUTE FUNCTION record_insert();

CREATE TRIGGER audit_update_generic_instance_lineage
    AFTER UPDATE ON generic_instance_lineage
    FOR EACH ROW EXECUTE FUNCTION record_update();

-- Modified timestamp triggers (BEFORE UPDATE)
CREATE TRIGGER update_modified_dt_generic_template
    BEFORE UPDATE ON generic_template
    FOR EACH ROW EXECUTE FUNCTION update_modified_dt();

CREATE TRIGGER update_modified_dt_generic_instance
    BEFORE UPDATE ON generic_instance
    FOR EACH ROW EXECUTE FUNCTION update_modified_dt();

CREATE TRIGGER update_modified_dt_generic_instance_lineage
    BEFORE UPDATE ON generic_instance_lineage
    FOR EACH ROW EXECUTE FUNCTION update_modified_dt();
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

class tapdb_core(Base):
    """
    Abstract base class for all daylily-tapdb entities.

    Note: This was named 'bloom_core' in the original BLOOM LIMS codebase.
    Applications extending daylily-tapdb may alias this for compatibility.
    """

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
class generic_template(tapdb_core):
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


class workflow_step_template(generic_template):
    """Template for workflow step objects."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_step_template'
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

class generic_instance(tapdb_core):
    """Base instance class with polymorphic inheritance."""

    __tablename__ = 'generic_instance'

    # Template reference
    template_uuid = Column(UUID(as_uuid=True), ForeignKey('generic_template.uuid'), nullable=False)

    # Relationships
    template = relationship('generic_template', foreign_keys=[template_uuid])

    # Lineage relationships (filtered to exclude soft-deleted edges)
    parent_of_lineages = relationship(
        'generic_instance_lineage',
        primaryjoin="and_(generic_instance.uuid==generic_instance_lineage.parent_instance_uuid, "
                    "generic_instance_lineage.is_deleted==False)",
        foreign_keys='generic_instance_lineage.parent_instance_uuid',
        back_populates='parent_instance'
    )
    child_of_lineages = relationship(
        'generic_instance_lineage',
        primaryjoin="and_(generic_instance.uuid==generic_instance_lineage.child_instance_uuid, "
                    "generic_instance_lineage.is_deleted==False)",
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


class workflow_step_instance(generic_instance):
    """Instance of a workflow step."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_step_instance'
    }


class equipment_instance(generic_instance):
    """Instance of equipment."""

    __mapper_args__ = {
        'polymorphic_identity': 'equipment_instance'
    }


class actor_instance(generic_instance):
    """Instance of an actor (user, organization, etc.)."""

    __mapper_args__ = {
        'polymorphic_identity': 'actor_instance'
    }
```

### 3.4 Lineage ORM Class

```python
class generic_instance_lineage(tapdb_core):
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

    # Relationships (filtered to exclude soft-deleted instances)
    parent_instance = relationship(
        'generic_instance',
        primaryjoin="and_(generic_instance_lineage.parent_instance_uuid==generic_instance.uuid, "
                    "generic_instance.is_deleted==False)",
        foreign_keys=[parent_instance_uuid],
        back_populates='parent_of_lineages'
    )
    child_instance = relationship(
        'generic_instance',
        primaryjoin="and_(generic_instance_lineage.child_instance_uuid==generic_instance.uuid, "
                    "generic_instance.is_deleted==False)",
        foreign_keys=[child_instance_uuid],
        back_populates='child_of_lineages'
    )

    __mapper_args__ = {
        'polymorphic_on': 'polymorphic_discriminator',
        'polymorphic_identity': 'generic_instance_lineage'
    }
```

### 3.6 Soft-Delete Filtering

All ORM relationships automatically exclude soft-deleted records. This ensures:

- Traversing lineage never returns deleted edges or nodes
- Templates marked as deleted are not returned in template queries
- Application code doesn't need manual `is_deleted=False` filters

For queries that need to include deleted records (e.g., audit views):

```python
# Include soft-deleted records explicitly
all_instances = session.query(generic_instance).filter(
    # No is_deleted filter - returns all records
).all()

# Or use a dedicated method
def get_including_deleted(session, model, **filters):
    """Query including soft-deleted records."""
    return session.query(model).filter_by(**filters).all()
```


---

## 4. Template System Specification

> **Note:** This specification describes the **daylily-tapdb v2** template format.
> While inspired by BLOOM LIMS, this format has been refined for clarity and
> extensibility. A conversion script will be provided to migrate existing BLOOM
> templates to the v2 format.

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

#### Action Imports vs Action Groups

**Templates** use `action_imports` to declare which actions are available:

```json
{
  "action_imports": {
    "set_object_status": "action/core/set_object_status/1.0/",
    "print_barcode_label": "action/core/print_barcode_label/1.0/"
  }
}
```

**Instances** use `action_groups` with fully materialized action definitions (copied from imports at instantiation):

```json
{
  "action_groups": {
    "core_actions": {
      "set_object_status": {
        "action_name": "Set Status",
        "method_name": "do_action_set_object_status",
        "action_enabled": "1",
        "action_executed": "0",
        ...
      }
    }
  }
}
```

The `InstanceFactory.create_instance()` method calls `materialize_actions()` to copy action definitions from imported action templates into the instance's `action_groups`:

```python
def materialize_actions(
    template: generic_template,
    template_manager: TemplateManager
) -> Dict[str, Any]:
    """
    Materialize action_imports into action_groups for an instance.

    Reads action template definitions and expands them into the format
    expected by ActionDispatcher.
    """
    action_groups = {}

    for action_key, template_code in template.json_addl.get('action_imports', {}).items():
        action_tmpl = template_manager.get_template(template_code)
        if action_tmpl:
            group_name = action_tmpl.btype  # e.g., 'core'
            if group_name not in action_groups:
                action_groups[group_name] = {}

            # Copy action definition with runtime tracking fields
            action_groups[group_name][action_key] = {
                **action_tmpl.json_addl.get('action_definition', {}),
                'action_executed': '0',
                'executed_datetime': [],
                'action_enabled': '1'
            }

    return action_groups
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

    def validate_template(self, template_data: Dict[str, Any]) -> List[str]:
        """
        Validate template data before loading.

        Args:
            template_data: Template dictionary (from JSON).

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []

        # Required fields
        required = ['super_type', 'btype', 'b_sub_type', 'version', 'instance_prefix']
        for field in required:
            if field not in template_data:
                errors.append(f"Missing required field: {field}")

        # Validate version format (semver-ish)
        version = template_data.get('version', '')
        if version and not self._is_valid_version(version):
            errors.append(f"Invalid version format: {version} (expected X.Y or X.Y.Z)")

        # Validate instance_prefix
        prefix = template_data.get('instance_prefix', '')
        if prefix and not prefix.isupper():
            errors.append(f"instance_prefix must be uppercase: {prefix}")

        # Validate json_addl structure
        json_addl = template_data.get('json_addl', {})
        if 'instantiation_layouts' in json_addl:
            for i, layout in enumerate(json_addl['instantiation_layouts']):
                if 'layout_string' not in layout:
                    errors.append(f"instantiation_layouts[{i}]: missing layout_string")

        # Validate action_imports reference valid template codes
        if 'action_imports' in json_addl:
            for action_key, template_code in json_addl['action_imports'].items():
                if not self._parse_template_code(template_code):
                    errors.append(f"action_imports[{action_key}]: invalid template code: {template_code}")

        return errors

    def _is_valid_version(self, version: str) -> bool:
        """Check if version string is valid (X.Y or X.Y.Z format)."""
        import re
        return bool(re.match(r'^\d+\.\d+(\.\d+)?$', version))
```

### 5.3 Instance Factory

```python
import copy

class InstanceFactory:
    """Factory for creating instances from templates."""

    # Maximum recursion depth for instantiation_layouts (prevents runaway cycles)
    MAX_INSTANTIATION_DEPTH = 10

    def __init__(self, db: TAPDBConnection, template_manager: TemplateManager):
        self.db = db
        self.template_manager = template_manager

    def create_instance(
        self,
        template_code: str,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        create_children: bool = True,
        _depth: int = 0  # Internal: tracks recursion depth
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

        Raises:
            ValueError: If template not found or max depth exceeded.
        """
        # Guard against infinite recursion
        if _depth > self.MAX_INSTANTIATION_DEPTH:
            raise ValueError(
                f"Max instantiation depth ({self.MAX_INSTANTIATION_DEPTH}) exceeded. "
                f"Check for cycles in instantiation_layouts."
            )

        template = self.template_manager.get_template(template_code)
        if not template:
            raise ValueError(f"Template not found: {template_code}")

        # Determine instance class based on polymorphic discriminator
        instance_class = self._get_instance_class(template.polymorphic_discriminator)

        # Deep copy template json_addl to avoid mutating template data
        json_addl = copy.deepcopy(template.json_addl)
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
            self._create_children(instance, template, _depth + 1)

        return instance

    def _create_children(
        self,
        parent: generic_instance,
        template: generic_template,
        depth: int
    ):
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
                    create_children=True,  # Recursive
                    _depth=depth  # Pass depth for cycle detection
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

## 6. Action System

The action system provides a mechanism for defining and executing operations on instances. **daylily-tapdb includes the abstract dispatcher, routing mechanism, and action instance types**; concrete action implementations are application-specific.

### 6.1 Action Instance as First-Class Object

Action instances (`XX` prefix) are **first-class audit and scheduling records**. Each action execution can optionally create an `action_instance` record that:

- Provides a centralized, queryable audit log
- Enables action scheduling for future execution
- Links to target objects via lineage relationships
- Stores captured data and execution results

```
┌─────────────────────┐         ┌─────────────────────────────┐
│  action_template    │         │  action_instance (XX prefix)│
│  GT99 (definition)  │────────▶│  XX5678                     │
│  "print_label"      │         │  bstatus: "complete"        │
└─────────────────────┘         │  json_addl: {               │
                                │    executed_by: "user@...", │
                                │    executed_at: "...",      │
                                │    captured_data: {...},    │
                                │    result: {...}            │
                                │  }                          │
                                └──────────────┬──────────────┘
                                               │ lineage (GL)
                                               ▼
                                ┌─────────────────────────────┐
                                │  container_instance (target)│
                                │  CX1234                     │
                                └─────────────────────────────┘
```

### 6.2 Action Instance Types

```python
class action_template(generic_template):
    """Template defining an action type."""
    __mapper_args__ = {
        'polymorphic_identity': 'action_template'
    }


class action_instance(generic_instance):
    """
    Record of an action execution or scheduled action.

    bstatus values:
        - 'scheduled': Pending future execution
        - 'pending': Ready to execute
        - 'in_progress': Currently executing
        - 'complete': Successfully executed
        - 'failed': Execution failed
        - 'cancelled': Cancelled before execution
    """
    __mapper_args__ = {
        'polymorphic_identity': 'action_instance'
    }


class action_instance_lineage(generic_instance_lineage):
    """Links action instances to target objects."""
    __mapper_args__ = {
        'polymorphic_identity': 'action_instance_lineage'
    }
```

### 6.3 Action Instance Structure

```json
{
  "super_type": "action",
  "btype": "core",
  "b_sub_type": "print_barcode_label",
  "version": "1.0",
  "bstatus": "complete",
  "json_addl": {
    "properties": {
      "executed_by": "user@example.com",
      "executed_at": "2026-01-19T14:30:00Z",
      "scheduled_for": null,
      "execution_time_ms": 150
    },
    "captured_data": {
      "printer_name": "lab_printer_1",
      "copies": 2
    },
    "result": {
      "success": true,
      "message": "Label printed successfully"
    },
    "target_euids": ["CX1234", "CX1235"]
  }
}
```

### 6.4 Action Dispatcher (Abstract Base)

```python
from abc import ABC
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm.attributes import flag_modified

class ActionDispatcher(ABC):
    """
    Abstract base class for action execution.

    Applications extend this class to implement concrete do_action_* methods.
    The dispatcher routes action requests to the appropriate handler method
    and optionally creates action_instance records for audit/scheduling.
    """

    def __init__(self, db: TAPDBConnection):
        self.db = db

    def execute_action(
        self,
        instance: generic_instance,
        action_group: str,
        action_key: str,
        action_ds: Dict[str, Any],
        captured_data: Optional[Dict[str, Any]] = None,
        create_action_record: bool = True,
        user: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Route action to appropriate handler method.

        Args:
            instance: The instance to act on.
            action_group: The action group name (e.g., 'core_actions').
            action_key: The action key within the group.
            action_ds: The action definition from json_addl.
            captured_data: User-provided data from action form.
            create_action_record: If True, create action_instance audit record.
            user: Username for audit purposes.

        Returns:
            Result dictionary with 'status', 'message', and optional 'action_euid'.

        Raises:
            ValueError: If method_name is invalid.
            NotImplementedError: If handler method not found.
        """
        method_name = action_ds.get("method_name")
        start_time = datetime.utcnow()

        # Validate method name follows convention
        if not method_name or not method_name.startswith("do_action_"):
            raise ValueError(f"Invalid action method: {method_name}")

        # Find handler method
        handler = getattr(self, method_name, None)
        if handler is None:
            raise NotImplementedError(
                f"Action not implemented: {method_name}. "
                f"Subclass must implement this method."
            )

        # Execute handler
        result = handler(instance, action_ds, captured_data or {})

        end_time = datetime.utcnow()
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

        # Update inline action tracking (legacy pattern)
        self._record_action_execution(instance, action_group, action_key, action_ds)

        # Create action_instance record if requested
        if create_action_record:
            action_record = self._create_action_instance(
                action_group=action_group,
                action_key=action_key,
                target_instances=[instance],
                captured_data=captured_data or {},
                result=result,
                user=user,
                execution_time_ms=execution_time_ms
            )
            result['action_euid'] = action_record.euid

        return result

    def _create_action_instance(
        self,
        action_group: str,
        action_key: str,
        target_instances: List[generic_instance],
        captured_data: Dict[str, Any],
        result: Dict[str, Any],
        user: Optional[str] = None,
        execution_time_ms: int = 0,
        scheduled_for: Optional[datetime] = None
    ) -> action_instance:
        """
        Create an action_instance record for audit/tracking.

        Args:
            action_group: The action group name.
            action_key: The action key (b_sub_type).
            target_instances: Instances this action was applied to.
            captured_data: User input data.
            result: Execution result.
            user: User who executed the action.
            execution_time_ms: Execution duration in milliseconds.
            scheduled_for: Future execution time (for scheduled actions).

        Returns:
            The created action_instance record.
        """
        now = datetime.utcnow()

        # Determine status based on result or scheduling
        if scheduled_for and scheduled_for > now:
            bstatus = 'scheduled'
        elif result.get('status') == 'success':
            bstatus = 'complete'
        else:
            bstatus = 'failed'

        # Find or create action template for this action type
        # Action templates use template_code: action/{group}/{key}/1.0/
        action_template = self._get_or_create_action_template(action_group, action_key)

        action_record = action_instance(
            name=f"{action_group}/{action_key}",
            template_uuid=action_template.uuid,  # Required FK to template
            btype=action_group,
            b_sub_type=action_key,
            version='1.0',
            super_type='action',
            polymorphic_discriminator='action_instance',
            bstatus=bstatus,
            json_addl={
                'properties': {
                    'executed_by': user,
                    'executed_at': now.isoformat() if not scheduled_for else None,
                    'scheduled_for': scheduled_for.isoformat() if scheduled_for else None,
                    'execution_time_ms': execution_time_ms
                },
                'captured_data': captured_data,
                'result': result,
                'target_euids': [inst.euid for inst in target_instances]
            }
        )

        self.db.session.add(action_record)
        self.db.session.flush()  # Get EUID assigned

        # Create lineage to target instances
        for target in target_instances:
            lineage = action_instance_lineage(
                name=f"{action_record.euid}->{target.euid}",
                parent_instance_uuid=action_record.uuid,
                child_instance_uuid=target.uuid,
                polymorphic_discriminator='action_instance_lineage',
                super_type='lineage',
                btype='action_lineage',
                b_sub_type='executed_on',
                version='1.0',
                bstatus='active',
                json_addl={}
            )
            self.db.session.add(lineage)

        return action_record

    def _get_or_create_action_template(
        self,
        action_group: str,
        action_key: str
    ) -> action_template:
        """
        Get or create an action_template for the given action type.

        Action templates are auto-created on first use if not pre-defined.
        """
        template_code = f"action/{action_group}/{action_key}/1.0/"

        existing = self.db.session.query(action_template).filter(
            action_template.super_type == 'action',
            action_template.btype == action_group,
            action_template.b_sub_type == action_key,
            action_template.version == '1.0',
            action_template.is_deleted == False
        ).first()

        if existing:
            return existing

        # Auto-create template for this action type
        new_template = action_template(
            name=f"{action_group}/{action_key}",
            super_type='action',
            btype=action_group,
            b_sub_type=action_key,
            version='1.0',
            instance_prefix='XX',
            polymorphic_discriminator='action_template',
            bstatus='ready',
            json_addl={
                'description': f"Auto-created template for {action_group}/{action_key}",
                'properties': {}
            }
        )

        self.db.session.add(new_template)
        self.db.session.flush()

        return new_template

    def schedule_action(
        self,
        instance: generic_instance,
        action_group: str,
        action_key: str,
        action_ds: Dict[str, Any],
        scheduled_for: datetime,
        captured_data: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None
    ) -> action_instance:
        """
        Schedule an action for future execution.

        Creates an action_instance with bstatus='scheduled'.
        Applications implement a scheduler to process these records.

        Args:
            instance: The target instance.
            action_group: The action group name.
            action_key: The action key.
            action_ds: The action definition.
            scheduled_for: When to execute the action.
            captured_data: Data to pass when executing.
            user: User scheduling the action.

        Returns:
            The scheduled action_instance record.
        """
        return self._create_action_instance(
            action_group=action_group,
            action_key=action_key,
            target_instances=[instance],
            captured_data=captured_data or {},
            result={'status': 'scheduled', 'message': 'Awaiting execution'},
            user=user,
            scheduled_for=scheduled_for
        )

    def _record_action_execution(
        self,
        instance: generic_instance,
        action_group: str,
        action_key: str,
        action_ds: Dict[str, Any]
    ):
        """Record that an action was executed (inline in target's json_addl)."""
        # Update execution count
        exec_count = int(action_ds.get("action_executed", "0")) + 1
        instance.json_addl["action_groups"][action_group][action_key]["action_executed"] = str(exec_count)

        # Record execution timestamp
        exec_times = action_ds.get("executed_datetime", [])
        exec_times.append(datetime.utcnow().isoformat())
        instance.json_addl["action_groups"][action_group][action_key]["executed_datetime"] = exec_times

        # Check max_executions and disable if reached
        max_exec = int(action_ds.get("max_executions", "-1"))
        if max_exec > 0 and exec_count >= max_exec:
            instance.json_addl["action_groups"][action_group][action_key]["action_enabled"] = "0"

        # Handle deactivate_actions_when_executed
        for deactivate_key in action_ds.get("deactivate_actions_when_executed", []):
            if deactivate_key in instance.json_addl["action_groups"].get(action_group, {}):
                instance.json_addl["action_groups"][action_group][deactivate_key]["action_enabled"] = "0"

        flag_modified(instance, "json_addl")
```

### 6.5 Querying Action History

Action instances enable powerful audit queries:

```python
# All actions executed today
today = datetime.utcnow().date()
actions_today = session.query(action_instance).filter(
    action_instance.created_dt >= today
).all()

# Actions by a specific user
user_actions = session.query(action_instance).filter(
    action_instance.json_addl['properties']['executed_by'].astext == 'user@example.com'
).all()

# Failed actions needing retry
failed_actions = session.query(action_instance).filter(
    action_instance.bstatus == 'failed'
).all()

# Scheduled actions ready to execute
pending = session.query(action_instance).filter(
    action_instance.bstatus == 'scheduled',
    action_instance.json_addl['properties']['scheduled_for'].astext <= datetime.utcnow().isoformat()
).all()

# Actions on a specific target (via lineage)
target_euid = 'CX1234'
target = session.query(generic_instance).filter_by(euid=target_euid).first()
actions_on_target = session.query(action_instance).join(
    action_instance_lineage,
    action_instance.uuid == action_instance_lineage.parent_instance_uuid
).filter(
    action_instance_lineage.child_instance_uuid == target.uuid
).all()
```

### 6.6 Application Implementation Pattern

Applications extend `ActionDispatcher` to implement concrete actions:

```python
# In your application (e.g., BLOOM LIMS)
from daylily_tapdb import ActionDispatcher, generic_instance

class BloomActionHandler(ActionDispatcher):
    """BLOOM-specific action implementations."""

    def do_action_set_object_status(
        self,
        instance: generic_instance,
        action_ds: dict,
        captured_data: dict
    ) -> dict:
        """Set the status of an object."""
        new_status = captured_data.get("object_status")
        if not new_status:
            return {"status": "error", "message": "No status provided"}

        instance.bstatus = new_status
        return {"status": "success", "message": f"Status set to {new_status}"}

    def do_action_print_barcode_label(
        self,
        instance: generic_instance,
        action_ds: dict,
        captured_data: dict
    ) -> dict:
        """Print a barcode label (BLOOM-specific, uses zebra_day)."""
        # This is application-specific - NOT in daylily-tapdb
        from bloom_lims.integrations import zebra_day
        # ... implementation
        return {"status": "success", "message": "Label printed"}
```

### 6.7 Action Definition in Templates

Actions are defined in the `json_addl.action_groups` structure:

```json
{
  "action_groups": {
    "core_actions": {
      "set_status": {
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
        "description": "Set the status of this object"
      }
    }
  }
}
```

---

## 7. Workflow System

The workflow system provides **polymorphic types for workflow and workflow_step objects**. Workflow execution logic (queuing, state machines, scheduling) is application-specific and NOT included in daylily-tapdb.

### 7.1 Workflow Types (Included)

```python
class workflow_template(generic_template):
    """Template for workflow definitions."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_template'
    }


class workflow_step_template(generic_template):
    """Template for workflow step definitions."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_step_template'
    }


class workflow_instance(generic_instance):
    """Instance of a workflow."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_instance'
    }


class workflow_step_instance(generic_instance):
    """Instance of a workflow step."""

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_step_instance'
    }
```

### 7.2 Workflow Template Structure

```json
{
  "super_type": "workflow",
  "btype": "assay",
  "b_sub_type": "ngs-library-prep",
  "version": "1.0",
  "json_addl": {
    "properties": {
      "workflow_type": "sequential",
      "estimated_duration_hours": 4
    },
    "instantiation_layouts": [
      {
        "layout_name": "steps",
        "layout_string": "workflow_step/step/extraction/1.0/",
        "count": 1,
        "naming_pattern": "{parent_name}_step_1",
        "lineage_type": "contains"
      }
    ]
  }
}
```

### 7.3 Workflow Execution (NOT Included)

The following are **application-specific** and NOT part of daylily-tapdb:

- Workflow state machines (pending → running → complete)
- Step execution queuing
- Parallel/sequential step orchestration
- Workflow scheduling and triggers
- Progress tracking and notifications

Applications implement these by extending the workflow types:

```python
# In your application
from daylily_tapdb import workflow_instance

class BloomWorkflow(workflow_instance):
    """BLOOM-specific workflow with execution logic."""

    def start(self):
        """Start workflow execution (application-specific)."""
        # Implementation depends on your execution model
        pass

    def advance_to_next_step(self):
        """Move to next step (application-specific)."""
        pass
```

---

## 8. EUID System

Enterprise Unique Identifiers (EUIDs) are **mandatory** in daylily-tapdb. They provide human-readable, type-prefixed identifiers that are easier to work with than UUIDs.

### 8.1 EUID Format

```
{PREFIX}{SEQUENCE_NUMBER}
```

**Examples:**
- `GT99` - Generic template #99
- `GX1234` - Generic instance #1234
- `GL5678` - Lineage relationship #5678
- `WX42` - Workflow instance #42
- `XX100` - Action execution record #100

### 8.2 Prefix Classification

EUID prefixes are organized into three tiers:

#### Core Prefixes (Required)

These prefixes are fundamental to the 3-table model and are always included:

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `GT` | template | All template records |
| `GX` | instance | Generic/fallback instance prefix |
| `GL` | lineage | Lineage relationships |

#### Optional Prefixes (Library Features)

These prefixes support optional library features (workflows, actions). Include them when using these features:

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `WX` | workflow | Workflow instances |
| `WSX` | workflow_step | Workflow step instances |
| `XX` | action | Action execution records |

#### Application Prefixes (User-Defined)

Domain-specific prefixes are configured by the application, not the library:

| Example Prefix | Super Type | Domain |
|----------------|------------|--------|
| `CX` | container | LIMS: plates, tubes, wells |
| `MX` | content | LIMS: samples, reagents |
| `EX` | equipment | LIMS: instruments |
| `AX` | actor | User/organization management |
| `FX` | file | File storage systems |

### 8.3 Pluggable Prefix Configuration

```python
from typing import Dict, Optional

class EUIDConfig:
    """
    Configure EUID prefixes per super_type.

    Core prefixes are always available. Optional and application-specific
    prefixes can be added via configuration.
    """

    # Core prefixes required by the 3-table model
    CORE_PREFIXES: Dict[str, str] = {
        "template": "GT",
        "instance": "GX",
        "lineage": "GL",
    }

    # Optional prefixes for library features
    OPTIONAL_PREFIXES: Dict[str, str] = {
        "workflow": "WX",
        "workflow_step": "WSX",
        "action": "XX",
    }

    def __init__(
        self,
        prefix_map: Optional[Dict[str, str]] = None,
        include_optional: bool = True
    ):
        """
        Initialize EUID configuration.

        Args:
            prefix_map: Custom prefix mapping. Merged with core/optional.
            include_optional: Include optional library prefixes (default: True).
        """
        self.prefix_map = {**self.CORE_PREFIXES}
        if include_optional:
            self.prefix_map.update(self.OPTIONAL_PREFIXES)
        if prefix_map:
            self.prefix_map.update(prefix_map)

    def get_prefix(self, super_type: str) -> str:
        """Get the EUID prefix for a super_type."""
        return self.prefix_map.get(super_type, "GX")  # Fallback to generic

    def register_prefix(self, super_type: str, prefix: str):
        """Register a custom prefix for a super_type."""
        if len(prefix) < 1 or len(prefix) > 5:
            raise ValueError("Prefix must be 1-5 characters")
        if not prefix.isalpha():
            raise ValueError("Prefix must be alphabetic")
        self.prefix_map[super_type] = prefix.upper()

    def get_sequence_name(self, prefix: str) -> str:
        """Get the database sequence name for a prefix."""
        return f"{prefix.lower()}_instance_seq"
```

### 8.4 Application Configuration Example (BLOOM LIMS)

```python
# bloom_lims/config/euid.py
from daylily_tapdb import EUIDConfig

BLOOM_EUID_CONFIG = EUIDConfig(
    prefix_map={
        # LIMS-specific prefixes
        "container": "CX",
        "content": "MX",
        "equipment": "EX",
        "actor": "AX",
        "file": "FX",
        "data": "DX",
        "test_requisition": "TRX",
        "subject": "SX",
        # Sub-type prefixes
        "well": "CWX",
        "reagent": "MRX",
        "control": "MCX",
    },
    include_optional=True  # Include WX, WSX, XX
)
```

### 8.5 Database Sequence Configuration

Each prefix requires a corresponding PostgreSQL sequence:

```sql
-- Core sequences (always required)
CREATE SEQUENCE generic_template_seq;      -- GT prefix
CREATE SEQUENCE generic_instance_seq;      -- GX prefix (fallback)
CREATE SEQUENCE generic_instance_lineage_seq;  -- GL prefix

-- Optional library sequences
CREATE SEQUENCE wx_instance_seq;           -- WX (workflow)
CREATE SEQUENCE wsx_instance_seq;          -- WSX (workflow_step)
CREATE SEQUENCE xx_instance_seq;           -- XX (action)

-- Application-specific sequences (example: BLOOM LIMS)
-- CREATE SEQUENCE cx_instance_seq;        -- CX (container)
-- CREATE SEQUENCE mx_instance_seq;        -- MX (content)
-- ... add sequences for each application prefix
```

### 8.6 EUID vs UUID

| Aspect | EUID | UUID |
|--------|------|------|
| **Format** | `GX1234` | `550e8400-e29b-41d4-a716-446655440000` |
| **Human-readable** | ✅ Yes | ❌ No |
| **Type-identifiable** | ✅ Yes (prefix) | ❌ No |
| **Globally unique** | ✅ Within database | ✅ Universally |
| **Primary key** | ❌ No (UUID is PK) | ✅ Yes |
| **External references** | ✅ Preferred | ⚠️ Use when needed |

**Design Decision:** EUIDs are mandatory. The UUID remains the primary key for database integrity, but EUIDs are the preferred identifier for:
- User interfaces
- API responses
- Log messages
- External integrations
- Barcode labels

---

## 9. Configuration & Integration

### 9.1 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TAPDB_DATABASE_URL` | PostgreSQL connection string | `postgresql://localhost/tapdb` |
| `TAPDB_CONFIG_PATH` | Path to template configuration | `./config` |
| `TAPDB_ECHO_SQL` | Enable SQL query logging | `false` |
| `TAPDB_POOL_SIZE` | Connection pool size | `5` |
| `TAPDB_MAX_OVERFLOW` | Max overflow connections | `10` |

### 9.2 Integration Patterns

#### As a Python Package Dependency

```python
# In your application
from daylily_tapdb import TAPDBConnection, TemplateManager, InstanceFactory
from daylily_tapdb.models import generic_instance, container_instance

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
from daylily_tapdb.models import generic_instance, generic_template

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
from daylily_tapdb import ActionDispatcher

class CustomActionHandler(ActionDispatcher):
    """Handler for custom actions."""

    def do_action_custom(self, instance: generic_instance, action_ds: dict, captured_data: dict) -> dict:
        """
        Execute a custom action.

        Args:
            instance: The instance to act on.
            action_ds: Action definition from template.
            captured_data: User-provided data from action form.

        Returns:
            Result dictionary with status and message.
        """
        # Implement custom logic
        instance.json_addl['properties']['custom_field'] = captured_data.get('value')
        flag_modified(instance, 'json_addl')

        return {'status': 'success', 'message': 'Action completed'}
```

### 9.3 Database Migration Strategy

#### Initial Setup

```bash
# Create database
createdb tapdb

# Apply schema
psql tapdb < schema/tapdb_schema.sql

# Load initial templates
python -m daylily_tapdb.cli load-templates --config ./config
```

#### Schema Versioning & Migrations

Use Alembic with **raw SQL execution** for migrations because triggers, sequences, and
PostgreSQL-specific features cannot be expressed in SQLAlchemy's migration DSL:

```python
# alembic/versions/001_initial.py
from alembic import op
from pathlib import Path

def upgrade():
    """Apply complete schema including triggers."""
    schema_path = Path(__file__).parent.parent.parent / 'schema' / 'tapdb_schema.sql'
    op.execute(schema_path.read_text())

def downgrade():
    """Drop all tables (triggers are dropped automatically)."""
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS generic_instance_lineage CASCADE")
    op.execute("DROP TABLE IF EXISTS generic_instance CASCADE")
    op.execute("DROP TABLE IF EXISTS generic_template CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS generic_template_seq CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS generic_instance_seq CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS generic_instance_lineage_seq CASCADE")
```

**Best Practice:** Keep the complete schema in `schema/tapdb_schema.sql` as the source of truth.
Alembic migrations reference this file rather than duplicating DDL. For incremental changes,
create new migration files with specific ALTER statements.

### 9.4 Performance Considerations

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

## 10. Development Guidelines

See [AGENT.md](./AGENT.md) for detailed development guidelines and AI assistant instructions.

### 10.1 Code Style

- Follow PEP 8 for Python code
- Use type hints for all function signatures
- Document all public APIs with docstrings
- Use `black` for formatting, `ruff` for linting

### 10.2 Testing Requirements

- Unit tests for all ORM models
- Integration tests for database operations
- Test coverage minimum: 80%
- Use pytest with fixtures for database setup

#### Integration Tests Require Real PostgreSQL

**SQLite cannot be used for integration tests** because daylily-tapdb relies on:

- PostgreSQL-specific triggers (`BEFORE DELETE`, `AFTER INSERT/UPDATE`)
- Sequences for EUID generation
- `gen_random_uuid()` from pgcrypto extension
- `JSONB` data type with GIN indexes
- Dynamic SQL via `EXECUTE format(...)`

Provide a `docker-compose.yml` for local development:

```yaml
# docker-compose.yml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: tapdb_test
      POSTGRES_USER: tapdb
      POSTGRES_PASSWORD: tapdb_test_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Test fixtures should connect to this database:

```python
# conftest.py
import pytest
from daylily_tapdb import TAPDBConnection

@pytest.fixture(scope="session")
def db_connection():
    """Provide database connection for integration tests."""
    db_url = os.environ.get(
        'TAPDB_TEST_DATABASE_URL',
        'postgresql://tapdb:tapdb_test_password@localhost:5432/tapdb_test'
    )
    conn = TAPDBConnection(db_url)

    # Apply schema (including triggers)
    conn.apply_schema()

    yield conn

    conn.close()
```

### 10.3 Commit Conventions

```
<type>(<scope>): <description>

Types: feat, fix, docs, style, refactor, test, chore
Scopes: models, schema, api, templates, cli, actions, euid
```

---

## 11. Repository Structure & Packaging

### 11.0 Public API Surface

#### Stable API (Semantic Versioning Applies)

The following exports are considered **public API** and follow semantic versioning:

| Module | Exports | Description |
|--------|---------|-------------|
| `daylily_tapdb` | `TAPDBConnection` | Database connection manager |
| `daylily_tapdb` | `TemplateManager` | Template loading and caching |
| `daylily_tapdb` | `InstanceFactory` | Instance creation from templates |
| `daylily_tapdb` | `ActionDispatcher` | Action execution base class |
| `daylily_tapdb` | `EUIDConfig` | EUID prefix configuration |
| `daylily_tapdb.models` | All ORM classes | `tapdb_core`, `generic_*`, typed classes |

#### Internal (May Change Without Notice)

The following are implementation details and may change between minor versions:

| Module | Description |
|--------|-------------|
| `daylily_tapdb.templates.parser` | Template code parsing utilities |
| `daylily_tapdb.templates.loader` | JSON file loading internals |
| `daylily_tapdb._version` | Version info internals |
| Methods prefixed with `_` | All private methods |

**Rule:** If it's not exported from `daylily_tapdb.__init__.py`, it's internal.

### 11.1 Recommended Repository Structure

```
daylily-tapdb/
├── README.md                    # Quick start and overview
├── SPECIFICATION.md             # This document
├── AGENT.md                     # AI assistant guidelines
├── LICENSE                      # MIT License
├── pyproject.toml               # Package configuration
│
├── daylily_tapdb/               # Main package (underscore for Python import)
│   ├── __init__.py              # Package exports
│   ├── _version.py              # Version info
│   ├── connection.py            # TAPDBConnection class
│   ├── euid.py                  # EUIDConfig class
│   ├── models/                  # ORM models
│   │   ├── __init__.py
│   │   ├── base.py              # tapdb_core abstract class
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
│   │   └── dispatcher.py        # ActionDispatcher (abstract base)
│   └── cli/                     # Command-line interface
│       ├── __init__.py
│       └── main.py
│
├── schema/                      # Database schema
│   ├── tapdb_schema.sql         # Complete DDL
│   └── migrations/              # Alembic migrations
│
├── tests/                       # Test suite
│   ├── conftest.py              # Pytest fixtures
│   ├── test_models.py
│   ├── test_templates.py
│   ├── test_factory.py
│   ├── test_actions.py
│   ├── test_euid.py
│   └── test_integration.py
│
├── docs/                        # Documentation
│   ├── api/                     # API reference
│   └── examples/                # Usage examples
│
└── examples/                    # Example applications
    └── minimal_lims/            # Minimal working example
```

**Note:** The repository is named `daylily-tapdb` (hyphen) but the Python package is `daylily_tapdb` (underscore) for valid Python imports.

### 11.2 Package Configuration (pyproject.toml)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "daylily-tapdb"
version = "1.0.0"
description = "Templated Abstract Polymorphic Database - A flexible object model library"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.10"
authors = [
    {name = "Daylily Informatics", email = "info@daylilyinformatics.com"}
]
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
keywords = ["database", "orm", "polymorphic", "templates", "sqlalchemy", "lims"]

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
daylily-tapdb = "daylily_tapdb.cli:main"

[project.urls]
Homepage = "https://github.com/Daylily-Informatics/daylily-tapdb"
Repository = "https://github.com/Daylily-Informatics/daylily-tapdb.git"
Documentation = "https://daylily-tapdb.readthedocs.io"

[tool.setuptools.packages.find]
where = ["."]
include = ["daylily_tapdb*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --cov=daylily_tapdb"

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

### 11.3 Package Exports (__init__.py)

```python
"""
daylily-tapdb: Templated Abstract Polymorphic Database

A flexible, template-driven object model library for Python applications.
Extracted from BLOOM LIMS by Daylily Informatics.
"""

from daylily_tapdb._version import __version__
from daylily_tapdb.connection import TAPDBConnection
from daylily_tapdb.euid import EUIDConfig
from daylily_tapdb.actions import ActionDispatcher
from daylily_tapdb.models import (
    tapdb_core,
    generic_template,
    generic_instance,
    generic_instance_lineage,
    container_template,
    container_instance,
    content_template,
    content_instance,
    workflow_template,
    workflow_instance,
    workflow_step_template,
    workflow_step_instance,
    equipment_template,
    equipment_instance,
    actor_template,
    actor_instance,
)
from daylily_tapdb.templates import TemplateManager
from daylily_tapdb.factory import InstanceFactory

__all__ = [
    "__version__",
    "TAPDBConnection",
    "TemplateManager",
    "InstanceFactory",
    "EUIDConfig",
    "ActionDispatcher",
    "tapdb_core",
    "generic_template",
    "generic_instance",
    "generic_instance_lineage",
    "container_template",
    "container_instance",
    "content_template",
    "content_instance",
    "workflow_template",
    "workflow_instance",
    "workflow_step_template",
    "workflow_step_instance",
    "equipment_template",
    "equipment_instance",
    "actor_template",
    "actor_instance",
]
```

---

## Appendix A: EUID Prefix Registry

### Core Prefixes (Required)

These prefixes are included in `EUIDConfig.CORE_PREFIXES` and are always available:

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `GT` | template | All generic templates |
| `GX` | instance | Generic/fallback instance prefix |
| `GL` | lineage | Lineage relationships |

### Optional Library Prefixes

These prefixes are included in `EUIDConfig.OPTIONAL_PREFIXES` for optional library features:

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `WX` | workflow | Workflow instances |
| `WSX` | workflow_step | Workflow step instances |
| `XX` | action | Action execution/scheduling records |

### Example Application Prefixes (BLOOM LIMS)

These prefixes are **not** included in daylily-tapdb; applications configure them:

| Prefix | Super Type | Description |
|--------|------------|-------------|
| `CX` | container | Containers (plates, tubes, boxes) |
| `MX` | content | Materials/content (samples, reagents) |
| `EX` | equipment | Equipment/instruments |
| `AX` | actor | Actors (users, organizations) |
| `FX` | file | File references |
| `DX` | data | Data records |
| `TRX` | test_requisition | Test requisitions |
| `SX` | subject | Subjects (patients, samples) |
| `CWX` | well | Container wells |
| `MRX` | reagent | Reagent content |
| `MCX` | control | Control content |

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
| **Action Instance** | First-class record of an action execution or scheduled action |
| **json_addl** | JSONB column storing flexible, schema-free data |

---

## Appendix C: Migration from BLOOM

If migrating from BLOOM LIMS to use daylily-tapdb as a dependency:

### Class Name Changes

| BLOOM | daylily-tapdb |
|-------|---------------|
| `bloom_core` | `tapdb_core` |
| `BloomObj` | Application-specific (extend `tapdb_core`) |

### Import Changes

```python
# Before (BLOOM)
from bloom_lims.db import bloom_core, generic_instance

# After (daylily-tapdb)
from daylily_tapdb import tapdb_core, generic_instance

# For backward compatibility in BLOOM:
from daylily_tapdb import tapdb_core as bloom_core
```

### EUID Prefix Migration

```python
# BLOOM configures its domain-specific prefixes
from daylily_tapdb import EUIDConfig

BLOOM_EUID_CONFIG = EUIDConfig(
    prefix_map={
        "container": "CX",
        "content": "MX",
        "equipment": "EX",
        "actor": "AX",
        "file": "FX",
        # ... other LIMS-specific prefixes
    }
)
```

### Action Handler Migration

```python
# Before (BLOOM) - actions in BloomObj, logged in json_addl
class BloomObj:
    def do_action_set_object_status(self, ...):
        # Result logged only in target's json_addl["action_log"]
        ...

# After (daylily-tapdb) - extend ActionDispatcher with first-class action records
from daylily_tapdb import ActionDispatcher

class BloomActionHandler(ActionDispatcher):
    def do_action_set_object_status(self, instance, action_ds, captured_data):
        # Result logged in json_addl AND as action_instance (XX) record
        ...
```

### Lineage Prefix Note

BLOOM's actual lineage prefix is `GL`, not `LX`. The specification now correctly uses `GL`.

---

*Document version 1.2.0 — daylily-tapdb Library Specification*
*Extracted from BLOOM LIMS by Daylily Informatics*

See also: [TAPDB CLI Specification](TAPDB_CLI_SPECIFICATION.md)
