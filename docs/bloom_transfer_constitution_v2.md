
# LSMC / Bloom Material Transfer Algebra Constitution
Status: Draft (Revised)  
Scope: Bloom wet‑lab material execution layer  
Authority: Defines the mechanical rules governing physical material movement and lineage

---

# 1. Purpose

This document defines the **mechanical transfer algebra** used by Bloom to represent the
physical movement, transformation, and accumulation of materials in the lab.

The goal is to ensure:

- All physical movements are represented deterministically
- Material lineage is **append‑only**
- Container occupancy is unambiguous
- Containers may persist while **content identities evolve**
- Execution coordination (queues/workers) never becomes the source of physical truth

The system operates under **Option B identity law**:

> Whenever the contents of a container change, a **new material/content EUID is minted**.

This guarantees that **physical history is never rewritten** and that lineage always captures
the full evolution of material state.

---

# 2. Core Laws

## Law 1 — Single Current Occupancy

A terminal container (tube or well) may have **at most one current content instance**.

Historical occupants remain discoverable through lineage.

## Law 2 — Destination Identity

Any transfer output creates a **new material/content EUID**.

## Law 3 — No Shared Identity

A material/content EUID may appear in **only one container placement**.

## Law 4 — Transfer Implies Mint

All transfer operations produce **new content identities**.

## Law 5 — Lineage is Mandatory

Every output content instance must link to its parent content.

## Law 6 — Input Fate Must Be Declared

Each input must specify its fate:

- UNCHANGED
- PARTIALLY_CONSUMED
- FULLY_CONSUMED
- DISCARDED
- QUARANTINED

## Law 7 — Append‑Only Truth

Material history is append‑only. Corrections produce **new transfer actions**.

## Law 8 — Queue State is Not Physical Truth

Queues coordinate work but **do not define material reality**.

Material truth exists only in:

- transfer actions
- lineage edges
- container occupancy

---

# 3. Domain Objects

## Container

A physical carrier or addressable location.

Examples:

- tube
- plate well
- rack slot
- instrument position

A **plate is a composite container** whose wells are the terminal containers.

Terminal containers:

- tube
- well

## Material / Content

A physical content instance occupying a container.

Examples:

- specimen
- extracted DNA
- library material
- sequencing pool

## Placement

A read model describing which container currently holds a content instance.

Placement is derived from:

transfer actions → lineage → container

---

# 4. Transfer Primitives

The transfer algebra contains exactly **three primitives**.

## 4.1 Transfer (1 → 1)

Move some or all of a source content into a destination container.

Inputs

- 1 source content
- 1 destination container

Outputs

- 1 new content instance

Example

tube A → tube B

Result

MX1 → MX2  
MX2 DERIVED_FROM MX1

Transfer may also target **the same container**, creating a new content identity in place.

---

## 4.2 Split (1 → N)

Create multiple outputs from a single source.

Inputs

- 1 source
- N destination containers

Outputs

- N new content instances

Example

tube → 96 wells

---

## 4.3 Merge (N → 1)

Combine multiple sources into one destination container.

Inputs

- N source contents
- 1 destination container

Outputs

- 1 new content instance

Example

library A + library B + library C → pool tube

---

# 5. Container Occupancy Model

Containers may experience **multiple content generations over time**.

Example:

tube CX10

MX100 → MX101 → MX102

Each new instance **supersedes** the previous occupant.

---

# 6. Occupied‑Container Rule

Transfer outputs may bind to:

1. an **empty container**
2. an **occupied container**

If the container is occupied:

- the current occupant **must be included as an input parent**
- a new content EUID is minted
- the new output becomes the current occupant

Example

tube CX10 contains MX100

Add enzyme MX200:

merge([MX100, MX200]) → MX101 in CX10

Lineage

MX101 DERIVED_FROM MX100  
MX101 DERIVED_FROM MX200

MX101 becomes the new current occupant of CX10.

---

# 7. Transfer Planning Modes

Above the transfer algebra is a **destination resolution layer**.

Two axes exist.

## Allocation Mode

- AUTO
- DIRECTED

## Container Origin

- NEW_CONTAINER
- EXISTING_CONTAINER

Resulting modes:

| Mode | Allocation | Container |
|-----|------------|-----------|
| Auto → New | AUTO | NEW_CONTAINER |
| Auto → Existing | AUTO | EXISTING |
| Directed → New | DIRECTED | NEW_CONTAINER |
| Directed → Existing | DIRECTED | EXISTING |

---

# 8. Mapping Contract

Every transfer operation returns a mapping between sources and destinations.

Transfer

[source container + content] → [destination container + content]

Split

[source container + content] → [destination container + content]...

Merge

[source container + content]... → [destination container + content]

---

# 9. Lineage Vocabulary

Canonical edges:

DERIVED_FROM  
INPUT_OF  
OUTPUT_OF  
PLACED_IN

Optional projection edges:

SUPERSEDES_IN_CONTAINER

---

# 10. Queue Runtime Model

Queues coordinate work but **never represent physical truth**.

Minimal runtime objects.

## Queue

Defines eligibility rules.

Fields

queue_key  
subject_type  
required_capabilities

## Worker

Represents operator, service, or instrument.

Fields

worker_key  
capabilities  
status

## Claim

Temporary ownership of work.

Fields

claim_euid  
subject_euid  
worker_key  
started_at  
expires_at

## Hold (optional)

Prevents dispatch.

Fields

subject_euid  
reason  
created_at

---

# 11. Execution Flow

queue subject  
↓  
worker claims subject  
↓  
worker performs transfer primitive  
↓  
new content objects minted  
↓  
lineage recorded  
↓  
queue next subject

Queues coordinate execution but **never store physical truth**.

---

# 12. Consequences of Option B

Benefits

- Exact physical audit trail
- No ambiguous movement semantics
- Pooling and splitting explicit in lineage
- Easier reconciliation after operator mistakes
- Better regulatory traceability

Costs

- More content objects
- More lineage edges
- Need projections for UI

---

# 13. Summary

Transfer algebra:

transfer  
split  
merge

Container rule:

every change in container contents creates a new content identity

Execution coordination:

queue  
worker  
claim  
hold

Physical truth resides only in:

transfer actions  
lineage edges  
container occupancy
