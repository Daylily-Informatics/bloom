# AGENTS.md

## Purpose

This file defines how **AI coding agents (Augment Code in VS Code using ChatGPT 5.2)** must interact with this repository when performing the BLOOM → TapDB refactor.

It establishes:
- Which documents are authoritative
- What agents are allowed vs forbidden to change
- How to sequence work safely
- When to stop and ask for human review

This file is binding for all automated or semi‑automated refactors.

---

## Canonical Documents

### 1. Source of Truth (IMMUTABLE)

**`BLOOM_DATABASE_REFACTOR_PLAN_VERBATIM.md`**

- This document is the authoritative technical plan.
- It must be treated as **read‑only** by agents.
- Agents may **annotate it only via comments in code, PR descriptions, or separate notes**, never by editing the file itself.
- If ambiguity or contradiction is detected, agents must STOP and request clarification.

### 2. Execution Guide (DERIVED)

**`BLOOM_DATABASE_REFACTOR_PLAN_AUGMENT.md`**

- This document is a derived, execution‑oriented guide.
- It may be updated or regenerated *only* if the verbatim plan is unchanged.
- In case of conflict, the **verbatim plan always wins**.

---

## Allowed Operations

Agents MAY:

- Perform strictly mechanical refactors described in the plan
- Add new files explicitly listed (e.g. `tapdb_adapter.py`, `bloom_prefix_sequences.sql`)
- Move or delete files *only* when the plan explicitly reaches that phase
- Add SQLAlchemy synonyms and class aliases as specified
- Update scripts and docs to reference TapDB instead of legacy schema

Agents MAY annotate by:

- Code comments explaining how a change maps to the verbatim plan
- PR descriptions referencing section/phase numbers
- Temporary TODO comments **only if removed before final phase completion**

---

## Forbidden Operations

Agents MUST NOT:

- Rename or remove domain fields globally (`super_type`, `btype`, `b_sub_type`)
- Introduce new abstractions, helpers, or frameworks
- Redesign schemas, polymorphism, or inheritance
- Add migrations or live‑data handling logic
- Change runtime semantics (EUIDs, transactions, relationships)
- Modify `BLOOM_DATABASE_REFACTOR_PLAN_VERBATIM.md`

If any of the above seem necessary, the agent must STOP.

---

## Phase Discipline

Agents must work **strictly in phase order**:

1. Phase 0 — Dependency wiring
2. Phase 1 — TapDB adapter creation
3. Phase 2 — DB entrypoint flip
4. Phase 3 — Schema/bootstrap switch
5. Phase 4 — Seed + docs cleanup
6. Phase 5 — Legacy removal

Rules:
- Do not start Phase N+1 until Phase N validations pass.
- Do not mix changes across phases in a single commit.
- Prefer small, reviewable commits aligned to phases.

---

## Validation Gates (Hard Stops)

Agents must stop and report if any of the following fail:

- Imports fail after Phase 1 or 2
- Schema application fails after Phase 3
- EUID generation errors occur
- Seed scripts rely on deleted legacy files
- Tests or smoke checks regress behavior

No automatic "fix‑forward" is allowed past a failed gate.

---

## Communication Expectations

When uncertain, agents should:

- Quote the exact section of the verbatim plan
- Describe the ambiguity precisely
- Propose at most **one** interpretation

Do not silently choose between interpretations.

---

## Success Definition

The task is complete when:

- BLOOM runs end‑to‑end using **daylily‑tapdb**
- No legacy DB code or schema remains
- All call sites are unchanged
- Runtime behavior is identical
- The verbatim plan remains intact and unedited

---

*This file exists to keep automation boring, safe, and reversible.*

