
# LSMC / Bloom Queue Management for Container-Based Transfer Algebra

Status: Draft  
Scope: Work coordination layer for Bloom material execution  
Related Document: LSMC Bloom Transfer Algebra Constitution (v2)

---

# 1. Purpose

This document defines how **work queues operate** in Bloom given the material model defined in the transfer algebra constitution.

Key architectural principles:

- Containers persist through time
- Contents inside containers evolve through successive transfer actions
- Each content change produces a **new content EUID**
- Work queues coordinate execution but **do not represent physical truth**

The queue system therefore schedules work on **physical carriers (containers)** rather than on evolving content identities.

---

# 2. Core Queue Principle

## Queue Subject = Terminal Container

The default subject for execution queues is the **terminal container**:

- tube
- plate well

Workers operate on physical carriers, not abstract material identities.

Queue items therefore reference:

```
terminal_container_euid
```

At execution time the system resolves:

```
container -> current occupant content
```

---

# 3. Container vs Content Responsibilities

| Object | Role |
|------|------|
| Container | Persistent physical carrier |
| Content | Versioned instance of material inside container |
| Queue | Coordinates work on containers |
| Transfer Action | Creates new content identities |
| Lineage Graph | Tracks content derivation history |

Queue state never determines container contents.

Content identity is determined exclusively by **transfer actions**.

---

# 4. Claim-Time Content Resolution

When a worker claims a queue item:

1. The container subject is locked.
2. The system resolves the container's **current occupant content EUID**.
3. The worker verifies the content state is valid for the operation.
4. The worker performs the transfer primitive.
5. The resulting output content becomes the new container occupant.
6. The next queue step is scheduled.

Example:

```
Queue Subject: CX10

Claim:
resolve occupant -> MX102
execute operation
produce -> MX103 in CX10
```

The queue subject (`CX10`) never changes even though content evolves.

---

# 5. Container Content Evolution Example

Example tube over time:

```
CX10
  MX100 -> MX101 -> MX102 -> MX103
```

Each step represents a transfer action that created a new content identity.

The queue subject remains:

```
CX10
```

---

# 6. Queue Runtime Objects

The queue system remains intentionally minimal.

## Queue

Defines eligibility rules.

Fields:

```
queue_key
subject_type
required_capabilities
priority
```

Example:

```
extraction_input
library_prep_input
pool_assembly
run_loading
```

---

## Worker

Represents a technician, instrument, or service.

Fields:

```
worker_key
capabilities
status
```

---

## Claim

Represents temporary ownership of work.

Fields:

```
claim_euid
subject_euid
worker_key
started_at
expires_at
expected_operation
attempt_count
```

Derived state:

```
RUNNING = claim exists
```

---

## Hold (Optional)

Prevents dispatch.

Fields:

```
subject_euid
reason
created_at
```

---

# 7. Queue Subject State Model

Possible states:

```
READY
CLAIMED
HELD
FAILED_RETRYABLE
FAILED_TERMINAL
COMPLETED
```

RUNNING is derived from an active claim.

---

# 8. Multi-Container Operations

Some operations require multiple inputs.

Example:

```
CX1 + CX2 + CX3 -> CX4
```

These cannot be represented by queueing a single container.

## Solution: Operation Group Subjects

Introduce a lightweight **operation group object** that references the participating containers.

Example:

```
operation_group_euid
sources = [CX1, CX2, CX3]
destination_plan = CX4
operation = merge
```

The queue subject becomes:

```
operation_group_euid
```

Worker claim flow:

1. Claim operation group
2. Resolve current contents of all source containers
3. Validate eligibility
4. Execute merge transfer
5. Produce destination content
6. Schedule next queue step

---

# 9. Queue Execution Flow

```
queue subject
    ↓
worker claims subject
    ↓
resolve container occupants
    ↓
execute transfer primitive
    ↓
new content instances minted
    ↓
lineage recorded
    ↓
schedule next subject
```

Queues coordinate work but **never define physical truth**.

---

# 10. Design Advantages

Container-anchored queues provide:

- Stable queue subjects even as content evolves
- Simplified scheduling logic
- Clean separation between work coordination and material truth
- Deterministic execution semantics
- Reduced queue churn
- Better alignment with physical lab operations

---

# 11. What Not To Do

Avoid the following anti-patterns:

### Queueing Content EUIDs

Content identities change frequently and should not anchor queue subjects.

### Encoding Physical Truth in Queue State

Queue membership must never define what material exists.

### Using Workflow Graphs

Bloom uses **transfer primitives + queue coordination**, not traditional workflow engines.

---

# 12. Summary

Work coordination uses:

```
queue
worker
claim
hold
```

Queue subjects are:

```
terminal_container_euid
```

Except for multi-container operations which use:

```
operation_group_euid
```

Content evolution remains governed by the **transfer algebra**.

Queues merely coordinate execution.
