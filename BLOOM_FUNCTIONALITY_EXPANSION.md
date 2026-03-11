1. System overview

This specification defines a TapDB-native queue execution subsystem for Bloom. It uses only TapDB templates, TapDB objects, TapDB lineage links, and TapDB actions. It does not introduce queue tables, relational workflow tables, Redis, Celery, or any other persistence layer. Queue membership is a derived read model over authoritative object state plus active hold/lease objects; queue objects are configuration, not workflow truth. The Data Plane remains append-only evidence, execution systems record work but do not interpret or decide, R² remains the only decision authority for QC/disposition/release, and event delivery is at-least-once with idempotent consumers and aggregate-scoped ordering. EUIDs are opaque. 

LSMC_architecture_principles

 

LSMC_appendix_D_system_planes_c…

 

LSMC_appendix_C_domain_events_a…

 

LSMC_appendix_B_euid_xid_govern…

Hard constraint added by this spec: object relationships in TapDB are allowed only by lineage links. No relationship is authoritative unless it exists as a lineage link. Any EUID/key copied into json_addl is lookup metadata only and MUST NOT be treated as the source of truth for relationships.

The same queue subsystem must work for wet-lab orchestration and compute orchestration. The LSMC product set explicitly uses the same Data Plane across physical specimen workflows and computational analysis/reprocessing workflows, so the execution system must be generic across subject template types. 

LSMC_products

 

LSMC_products

1.1 Non-negotiable invariants

Codex MUST implement these invariants exactly:

Every work-bearing subject object stores its authoritative execution state on the subject object itself.

Queue membership is derived from subject state, queue definition, and active hold/lease lineage.

Queue objects are never authoritative for workflow state.

Exclusivity is enforced only through queue_lease objects and lineage.

Per-attempt proof is stored in execution_record.

All mutations occur through TapDB actions only.

All object relationships are lineage links only.

JSON fields like subject_euid, worker_euid, or queue_key may exist only as denormalized lookup metadata; they are not relationships.

Retries and duplicate delivery are normal; idempotency is required.

A stale or missing queue cache must not affect correctness.

No code may infer behavior from EUID prefix. 

LSMC_overview

 

LSMC_appendix_B_euid_xid_govern…

1.2 Required repository shape

Codex SHOULD implement the subsystem in the current Bloom repository using these modules/files:

bloom_lims/config/data/execution.json

bloom_lims/config/actor/system_worker.json (or equivalent actor config file)

bloom_lims/domain/execution_queue.py

bloom_lims/schemas/execution_queue.py

bloom_lims/api/v1/execution_queue.py

action template registration in a new execution action module or by extending the existing beta action module

refactor current beta queue operations so they call the new action/service path

preserve current beta API endpoints as compatibility wrappers until callers migrate

1.3 Work-bearing subject execution envelope

Every work-bearing subject object MUST contain this structure at:

subject.json_addl.properties.execution

{
  "state": "PENDING|READY|RUNNING|WAITING_EXTERNAL|FAILED_RETRYABLE|FAILED_TERMINAL|HELD|CANCELED|COMPLETED",
  "revision": 1,
  "next_queue_key": null,
  "next_action_key": null,
  "priority": 0,
  "ready_at": null,
  "due_at": null,
  "attempt_count": 0,
  "max_attempts_override": null,
  "retry_at": null,
  "hold_state": "NONE|ACTIVE|TERMINAL",
  "hold_reason": null,
  "cancel_requested": false,
  "terminal": false,
  "last_execution_record_euid": null,
  "queue_cache": {
    "current_queue_key": null,
    "computed_at": null
  }
}

Authoritative fields: state, revision, next_queue_key, next_action_key, priority, ready_at, due_at, attempt_count, max_attempts_override, retry_at, hold_state, hold_reason, cancel_requested, terminal.

Non-authoritative fields: last_execution_record_euid, queue_cache.*.

2. Domain model

All persistent concepts MUST be implemented as TapDB templates/instances and linked only through lineage. No new database tables may be introduced.

2.1 Template: data/execution/queue/1.0

Purpose
Stores queue definition and policy. It never stores membership.

Instance identity
One active queue object per {tenant_id, queue_key}.

Template code
data/execution/queue/1.0

Prefix
Use a T&A-governed prefix if assigned; otherwise use the existing TapDB category default. Prefix is opaque. 

LSMC_appendix_B_euid_xid_govern…

Fields

{
  "queue_key": "extraction_prod",
  "display_name": "Extraction / Production",
  "enabled": true,
  "manual_only": false,
  "operator_visible": true,
  "dispatch_priority": 100,
  "subject_template_codes": ["content/material/specimen/1.0"],
  "eligible_states": ["READY", "FAILED_RETRYABLE"],
  "required_worker_capabilities": ["wetlab.extraction"],
  "site_scope": [],
  "platform_scope": [],
  "assay_scope": [],
  "lease_ttl_seconds": 900,
  "max_attempts_default": 5,
  "retry_policy": {
    "mode": "EXPONENTIAL_BACKOFF",
    "initial_delay_seconds": 60,
    "backoff_factor": 2.0,
    "max_delay_seconds": 3600
  },
  "selection_policy": {
    "order": [
      "priority_desc",
      "due_at_asc",
      "ready_at_asc",
      "created_dt_asc",
      "euid_asc"
    ]
  },
  "diagnostics_enabled": true,
  "revision": 1,
  "disabled_reason": null
}

Authoritative relationships (lineage only)

queue --execution_queue_lease--> queue_lease

queue --execution_queue_record--> execution_record

queue --execution_queue_hold--> execution_hold

optional queue --execution_queue_dead_letter--> dead_letter_record

Lookup-only metadata

queue_key

Required logical indexes

tenant_id + template_uid + queue_key

tenant_id + template_uid + enabled

tenant_id + template_uid + dispatch_priority

use existing GIN(json_addl) on generic instance for policy filters

Lifecycle rules

Created by seed or admin action only

Updated only by action

No delete; disable in place

queue_key immutable

subject_template_codes immutable after creation

Changing subject_template_codes requires replacement queue object and retirement of old one

lease_ttl_seconds, retry policy, capabilities, visibility, and dispatch priority are mutable

2.2 Template: data/execution/queue_lease/1.0

Purpose
Represents one exclusive claim of one subject by one worker.

Template code
data/execution/queue_lease/1.0

Fields

{
  "lease_token": "opaque-string",
  "queue_lookup_key": "extraction_prod",
  "subject_lookup_euid": "MX20001",
  "worker_lookup_euid": "AX1234",
  "status": "ACTIVE|RELEASED|COMPLETED|EXPIRED|ABANDONED|CANCELED",
  "claimed_at": "2026-01-05T12:00:00Z",
  "heartbeat_at": "2026-01-05T12:00:00Z",
  "expires_at": "2026-01-05T12:15:00Z",
  "released_at": null,
  "release_reason": null,
  "attempt_number": 1,
  "ttl_seconds": 900,
  "next_action_key": "create_extraction",
  "idempotency_key": "req-123",
  "subject_revision_at_claim": 4,
  "payload_hash": "sha256..."
}

Authoritative relationships (lineage only)

subject --execution_subject_lease--> queue_lease

worker --execution_worker_lease--> queue_lease

queue --execution_queue_lease--> queue_lease

queue_lease --execution_lease_record--> execution_record

Lookup-only metadata

queue_lookup_key

subject_lookup_euid

worker_lookup_euid

Required logical indexes

tenant_id + template_uid + subject_lookup_euid + status

tenant_id + template_uid + worker_lookup_euid + status

tenant_id + template_uid + queue_lookup_key + status + expires_at

tenant_id + template_uid + lease_token

tenant_id + template_uid + idempotency_key

Lifecycle rules

Created only by claim_queue_item

ACTIVE may transition only to RELEASED, COMPLETED, EXPIRED, ABANDONED, or CANCELED

Terminal lease states are immutable

New retry attempt always creates a new lease object

Expired lease remains persisted for audit

2.3 Template: actor/system/worker/1.0

Purpose
Persistent identity for a service worker, human session, or instrument adapter.

Template code
actor/system/worker/1.0

Fields

{
  "worker_key": "worker://bloom/wetlab/extractor-1",
  "display_name": "Wetlab Extractor 1",
  "worker_type": "SERVICE|HUMAN_SESSION|INSTRUMENT_ADAPTER",
  "status": "ONLINE|OFFLINE|DRAINING|DISABLED|RETIRED",
  "capabilities": ["wetlab.extraction", "site.sfo"],
  "site_scope": ["sfo"],
  "platform_scope": ["illumina"],
  "assay_scope": [],
  "max_concurrent_leases": 1,
  "heartbeat_at": "2026-01-05T12:00:00Z",
  "heartbeat_ttl_seconds": 60,
  "build_version": "gitsha-or-image-digest",
  "host": "pod-abc123",
  "process_identity": "pid-or-container-id",
  "drain_requested": false,
  "disabled_reason": null,
  "last_error_at": null,
  "last_error_class": null,
  "revision": 1
}

Authoritative relationships (lineage only)

worker --execution_worker_lease--> queue_lease

worker --execution_worker_record--> execution_record

Lookup-only metadata

worker_key

Required logical indexes

tenant_id + template_uid + worker_key

tenant_id + template_uid + status

tenant_id + template_uid + heartbeat_at

capabilities via GIN(json_addl)

Lifecycle rules

Upsert on startup via action

Heartbeat via action only

DRAINING allows heartbeat/release but no new claims

DISABLED allows no claims or renewals

OFFLINE may be computed from stale heartbeat

No delete; retire only

2.4 Template: data/execution/execution_record/1.0

Purpose
Immutable per-attempt proof record aligned with the documented ExecutionRecord contract artifact. 

LSMC_appendix_D_system_planes_c…

Template code
data/execution/execution_record/1.0

Fields

{
  "subject_lookup_euid": "MX20001",
  "queue_lookup_key": "extraction_prod",
  "worker_lookup_euid": "AX1234",
  "lease_lookup_euid": "DAT90001",
  "attempt_number": 1,
  "status": "STARTED|SUCCEEDED|FAILED_RETRYABLE|FAILED_TERMINAL|CANCELED|EXPIRED",
  "action_key": "create_extraction",
  "idempotency_key": "req-123",
  "payload_hash": "sha256...",
  "expected_state": "READY",
  "start_state": "READY",
  "end_state": "COMPLETED",
  "start_revision": 4,
  "end_revision": 5,
  "started_at": "2026-01-05T12:00:01Z",
  "finished_at": "2026-01-05T12:03:10Z",
  "duration_ms": 189000,
  "retryable": false,
  "error_class": null,
  "error_code": null,
  "error_message": null,
  "correlation": {
    "trx_euid": "TRX50001",
    "accession_euid": "ACC30001",
    "run_euid": "RUN80001",
    "step_euid": "STEP80002"
  },
  "input_snapshot": {},
  "result_snapshot": {},
  "policy_refs": []
}

Authoritative relationships (lineage only)

subject --execution_subject_record--> execution_record

queue --execution_queue_record--> execution_record

worker --execution_worker_record--> execution_record

queue_lease --execution_lease_record--> execution_record

optional execution_record --execution_record_output--> produced_object

optional execution_record --execution_record_supersedes--> earlier_execution_record

Lookup-only metadata

subject_lookup_euid

queue_lookup_key

worker_lookup_euid

lease_lookup_euid

correlation EUIDs

Required logical indexes

tenant_id + template_uid + subject_lookup_euid + started_at

tenant_id + template_uid + queue_lookup_key + status + started_at

tenant_id + template_uid + worker_lookup_euid + started_at

tenant_id + template_uid + action_key + idempotency_key

tenant_id + template_uid + lease_lookup_euid

Lifecycle rules

Created in STARTED when lease is claimed

May be updated exactly once to terminal status

started_at, attempt_number, expected_state, start_state, payload_hash are immutable

Corrections require a new record

2.5 Additional required templates
data/execution/hold/1.0

Used for operator hold / stop-the-line / integrity hold.

Fields

subject_lookup_euid

queue_lookup_key nullable

placed_by_lookup_euid

status=ACTIVE|RELEASED

hold_code

reason

placed_at

released_at

released_by_lookup_euid

Authoritative relationships

subject --execution_subject_hold--> execution_hold

optional queue --execution_queue_hold--> execution_hold

actor/worker --execution_actor_hold--> execution_hold

data/execution/dead_letter/1.0

Used when an item exceeds max attempts or hits terminal failure classification.

Fields

subject_lookup_euid

queue_lookup_key

last_execution_record_lookup_euid

last_lease_lookup_euid

dead_lettered_at

failure_count

error_class

error_message

resolution_state=OPEN|REQUEUED|CANCELED|IGNORED

resolved_by_lookup_euid

resolved_at

Authoritative relationships

subject --execution_subject_dead_letter--> dead_letter_record

queue --execution_queue_dead_letter--> dead_letter_record

execution_record --execution_record_dead_letter--> dead_letter_record

3. Queue semantics
3.1 Authoritative queue visibility rule

A subject is visible in queue Q if and only if all of the following are true:

subject.execution.next_queue_key == Q.queue_key

subject.execution.state IN Q.eligible_states

subject.execution.terminal == false

subject.execution.cancel_requested == false

subject.execution.hold_state != "ACTIVE"

coalesce(subject.execution.retry_at, subject.execution.ready_at, subject.created_dt) <= now

subject template code is listed in Q.subject_template_codes

subject passes queue scope filters: tenant/site/platform/assay

there is no lineage-linked active nonexpired queue_lease

there is no lineage-linked active execution_hold

Queue visibility MUST NOT be derived from a queue-membership lineage edge.

3.2 Forbidden membership patterns

Codex MUST NOT implement any of these as authoritative:

queue --membership--> subject

subject.current_queue_euid as authoritative relationship

beta_work_item or similar as authoritative membership object

arrays of related object IDs in JSON without lineage links

3.3 Permitted non-authoritative projections

Codex MAY maintain these caches only:

subject.execution.queue_cache.current_queue_key

queue summary counters on queue object

subject.execution.last_execution_record_euid

All reads MUST remain correct if those caches are absent or stale. LSMC’s portal/read-model pattern is explicitly derived, not authored. 

LSMC_overview

3.4 Queue ordering

Deterministic ordering is required:

execution.priority descending

execution.due_at ascending, null last

coalesce(execution.retry_at, execution.ready_at, created_dt) ascending

created_dt ascending

euid ascending

3.5 Worker-visible filtering

Before a worker may claim from queue Q, all of these MUST hold:

Q.enabled == true

if worker type is SERVICE or INSTRUMENT_ADAPTER, Q.manual_only == false

worker capabilities include all Q.required_worker_capabilities

worker site/platform/assay scopes overlap queue scopes

worker status is not DISABLED

worker drain_requested is false

worker active lease count < max_concurrent_leases

3.6 Query patterns
List queue members

Pseudo-logic:

def list_queue_items(session, tenant_id, queue_key, now, limit, offset):
    queue = get_queue_by_key(session, tenant_id, queue_key)
    candidates = query_subjects(
        template_codes=queue.subject_template_codes,
        execution_state_in=queue.eligible_states,
        next_queue_key=queue.queue_key,
        ready_before=now
    )
    visible = []
    for subject in candidates:
        if has_active_hold_lineage(session, subject.uid):
            continue
        if has_active_nonexpired_lease_lineage(session, subject.uid, now):
            continue
        if subject.execution.cancel_requested or subject.execution.terminal:
            continue
        visible.append(subject)
    return stable_sort(visible)[offset:offset+limit]
Count queue depth

Use the same predicate; return count only.

Oldest job age

Use the same predicate; compute now - min(coalesce(retry_at, ready_at, created_dt)).

3.7 Example TapDB query logic

The implementation MUST constrain by template first and then use JSON filters plus lineage exclusion:

subject_query = (
    session.query(GenericInstance)
    .filter(GenericInstance.tenant_id == tenant_id)
    .filter(GenericInstance.is_deleted == False)
    .filter(GenericInstance.template_uid.in_(subject_template_uids))
    .filter(GenericInstance.json_addl["properties"]["execution"]["next_queue_key"].astext == queue_key)
    .filter(GenericInstance.json_addl["properties"]["execution"]["state"].astext.in_(eligible_states))
)

Then exclude any subject UID that has:

lineage to execution_hold where hold status is ACTIVE

lineage to queue_lease where lease status is ACTIVE and expires_at > now

4. Execution state machine
4.1 Authoritative object states

Use these exact values:

PENDING

READY

RUNNING

WAITING_EXTERNAL

FAILED_RETRYABLE

FAILED_TERMINAL

HELD

CANCELED

COMPLETED

4.2 Derived concurrency states

These are computed, not authored:

VISIBLE_IN_QUEUE

LEASED

LEASE_EXPIRED

Rules:

VISIBLE_IN_QUEUE = queue visibility predicate true

LEASED = lineage-linked queue_lease.status == ACTIVE and expires_at > now

LEASE_EXPIRED = lineage-linked queue_lease.status == ACTIVE and expires_at <= now

4.3 Generic transition table
Current authoritative state	Derived queue state	Action	Next authoritative state
PENDING	none	domain preparation / routing action	READY
READY	visible	claim_queue_item	READY (item disappears from queue because lease now exists)
READY + active lease	leased	domain start action	RUNNING
RUNNING	none	domain complete action, no next queue	COMPLETED
RUNNING	none	domain complete action, next queue assigned	READY
RUNNING	none	domain fail action, retryable	FAILED_RETRYABLE
FAILED_RETRYABLE and retry window elapsed	visible	claim_queue_item	FAILED_RETRYABLE
FAILED_RETRYABLE + active lease	leased	retry domain start action	RUNNING
any nonterminal	none	place_execution_hold	HELD
HELD	none	release_execution_hold	READY or FAILED_RETRYABLE
any nonterminal	none	cancel_subject_execution	CANCELED
any nonterminal after permanent error or max attempts	none	fail_queue_execution(retryable=false)	FAILED_TERMINAL
4.4 Wet-lab examples
Domain state	Queue	Action	Next state
accepted specimen	extraction_prod / extraction_rnd	create_extraction	extracted
extracted	post_extract_qc	record_post_extract_qc	qc_passed or HELD
qc_passed	ilmn_lib_prep / ont_lib_prep	create_library_prep	library_prepared
library_prepared	ilmn_seq_pool / ont_seq_pool	create_pool	pooled
pooled	ilmn_start_seq_run / ont_start_seq_run	create_run	run_started
4.5 Compute examples
Domain state	Queue	Action	Next state
analysis_request_registered	compute dispatch queue	start_analysis_run	RUNNING
RUNNING	none	record_analysis_artifacts	READY (next queue = analysis QC) or COMPLETED
analysis_qc_pending	analysis QC queue	record_analysis_qc	COMPLETED or FAILED_TERMINAL
4.6 Invalid transition prevention

Every mutating action MUST enforce all of the following:

requested expected_state equals current subject.execution.state

if request carries expected revision, it equals current subject.execution.revision

action template allows transition from that state

if lease required, supplied lease is lineage-linked to subject and worker, active, and unexpired

held subjects only allow release_execution_hold, cancel_subject_execution, or admin override

terminal states are immutable except explicit admin/operator requeue action

Failure mode: return deterministic conflict; do not mutate subject, lease, or record.

5. Worker architecture
5.1 Worker types

Implement three worker types:

SERVICE

HUMAN_SESSION

INSTRUMENT_ADAPTER

All are persistent worker objects.

5.2 Worker registration

Every worker MUST call register_worker on startup with:

worker_key

display_name

worker_type

capabilities

scopes

max concurrency

build version / image digest

host/process identity

register_worker MUST upsert by {tenant_id, worker_key}. Duplicate worker objects for the same key are forbidden.

5.3 Heartbeat behavior

Workers MUST heartbeat at interval <= min(heartbeat_ttl_seconds / 3, 30s) using heartbeat_worker.

Heartbeat updates:

heartbeat_at

diagnostics fields if supplied

operational status if currently ONLINE

Workers in DRAINING keep heartbeating but do not claim new work.

5.4 Queue selection logic

Deterministic worker polling algorithm:

load worker object

reject if DISABLED or RETIRED

if DRAINING, skip claim loop

load serviceable queues:

enabled

capability match

scope match

manual_only=false unless worker type is HUMAN_SESSION

sort queues by:

dispatch_priority desc

queue_key asc

claim from first queue that yields work

if none yield work, sleep poll_interval_ms

5.5 Worker execution loop
while True:
    heartbeat_worker(worker_euid)

    worker = load_worker(worker_euid)
    if worker.status in ["DISABLED", "RETIRED"]:
        break
    if worker.status == "DRAINING":
        sleep(poll_interval_ms)
        continue

    claim = None
    for queue in ordered_serviceable_queues(worker):
        claim = claim_queue_item(worker_euid, queue.queue_key)
        if claim:
            break

    if not claim:
        sleep(poll_interval_ms)
        continue

    try:
        run_domain_action(
            action_key=claim.next_action_key,
            subject_euid=claim.subject_lookup_euid,
            worker_euid=worker_euid,
            lease_euid=claim.euid,
            expected_state=get_subject_state(claim.subject_lookup_euid),
            idempotency_key=new_idempotency_key()
        )
    except RetryableExecutionError as e:
        fail_queue_execution(
            lease_euid=claim.euid,
            worker_euid=worker_euid,
            retryable=True,
            error_class=e.error_class,
            error_message=e.message
        )
    except TerminalExecutionError as e:
        fail_queue_execution(
            lease_euid=claim.euid,
            worker_euid=worker_euid,
            retryable=False,
            error_class=e.error_class,
            error_message=e.message
        )
5.6 Human worker behavior

HUMAN_SESSION workers are allowed to:

claim a specific subject selected in UI

claim from manual_only queues

release or complete only their own active lease unless admin override

6. Lease system
6.1 Lease lifecycle

State transitions:

created as ACTIVE

renewed by heartbeat/renew action

terminal states:

RELEASED

COMPLETED

EXPIRED

ABANDONED

CANCELED

No transition from terminal state back to ACTIVE.

6.2 Claim algorithm

Claim MUST be implemented as a single transaction.

Algorithm:

load worker object FOR UPDATE

validate worker may claim

load queue definition

choose candidate subject:

either explicit subject from operator request

or first visible subject from ordered queue query

lock candidate subject row FOR UPDATE

re-evaluate visibility predicate under lock

resolve lineage-linked active leases for subject under lock

if any active nonexpired lease exists, abort claim with no-work/conflict

determine attempt_number = subject.execution.attempt_count + 1

create queue_lease object

create lineage:

subject -> queue_lease

worker -> queue_lease

queue -> queue_lease

create execution_record with status=STARTED

create lineage:

subject -> execution_record

worker -> execution_record

queue -> execution_record

queue_lease -> execution_record

optionally update non-authoritative queue cache on subject

record TapDB action instance

commit

6.3 Heartbeat and renew

renew_queue_lease MUST:

validate lease is lineage-linked to caller worker

validate lease status ACTIVE

validate expires_at > now

set:

heartbeat_at = now

expires_at = now + ttl_seconds

record action instance

Workers MUST renew at interval <= ttl_seconds/3.

6.4 Expiration semantics

A lease is expired when:

status == ACTIVE

expires_at <= now

Correctness rule: queue visibility queries MUST treat expired active leases as inactive even if no sweeper has updated status yet.

6.5 Reclaim behavior

Codex MUST implement a sweeper/admin action expire_queue_lease that:

finds active leases with expires_at <= now

marks them EXPIRED

sets released_at = now

sets release_reason = "HEARTBEAT_TIMEOUT"

This sweeper improves observability only. It is not required for correctness.

6.6 Exclusivity invariant

At most one active nonexpired lease may exist per subject.

This invariant MUST be enforced transactionally by:

locking the subject row before lease creation

rechecking lineage-linked leases under lock

only then creating the new lease and lineage

No uniqueness table or membership table may be added.

7. Action execution rules
7.1 Required action templates

Codex MUST add action templates for:

register_worker

heartbeat_worker

claim_queue_item

renew_queue_lease

release_queue_lease

complete_queue_execution

fail_queue_execution

place_execution_hold

release_execution_hold

requeue_subject

cancel_subject_execution

expire_queue_lease (admin/sweeper)

Existing domain actions such as extraction/QC/library/run creation MUST be executed through the same action framework and MUST NOT write directly around it.

7.2 Required action request envelope

Every mutating action request MUST carry:

subject_euid if applicable

worker_euid if applicable

lease_euid if applicable

expected_state

optional expected_revision

idempotency_key

request payload

payload hash or enough material to compute one server-side

7.3 Idempotency rules

Every mutating action MUST be idempotent.

Implementation rule:

before mutation, query existing execution_record by:

subject

action key

idempotency key

if found and payload hash matches:

return previously persisted result

do not create new lease or record

if found and payload hash differs:

return conflict

if not found:

proceed normally

Docs require at-least-once delivery, de-dup, and replay safety. This implementation MUST satisfy that requirement. 

LSMC_appendix_C_domain_events_a…

7.4 Atomic mutation rules

For any domain execution mutation, the following MUST commit or roll back together:

subject state mutation

subject revision increment

lease terminal update if applicable

execution record terminal update

lineage creation for new objects

action instance creation

outbox record/event if bus emission is enabled

7.5 Expected-state validation

Pseudo-logic:

def execute_with_state_guard(req):
    existing = find_existing_execution_record(req.subject_euid, req.action_key, req.idempotency_key)
    if existing:
        return replay_or_conflict(existing, req)

    subject = lock_subject(req.subject_euid)
    assert subject.execution.state == req.expected_state
    if req.expected_revision is not None:
        assert subject.execution.revision == req.expected_revision

    if action_requires_lease(req.action_key):
        lease = lock_lease(req.lease_euid)
        assert lease.status == "ACTIVE"
        assert lease.expires_at > now()
        assert lineage_exists(subject, lease, "execution_subject_lease")
        assert lineage_exists(worker, lease, "execution_worker_lease")

    apply_domain_mutation(subject, req.payload)
    subject.execution.revision += 1
    finalize_execution_record(...)
    finalize_lease_if_needed(...)
    create_action_instance(...)
7.6 External/irreversible work rule

For instrument dispatch or external pipeline kickoff, Codex MUST use a two-step pattern:

action sets subject state to WAITING_EXTERNAL and records external dispatch metadata

later callback/result action transitions from WAITING_EXTERNAL to READY, RUNNING, COMPLETED, or failure state

Do not pretend external side effects are inside the database transaction.

7.7 Outbox/event rule

If Bloom emits events, they MUST be produced via transactional outbox in the same transaction as the state change. The bus is transport, not truth. PHI must stay out of events by default. 

LSMC_appendix_C_domain_events_a…

 

LSMC_appendix_C_domain_events_a…

8. Failure handling
8.1 Worker crash

If a worker crashes after claim and before release:

lease eventually expires

queue visibility query treats expired lease as inactive

another worker may reclaim

old worker may not renew or complete the expired lease

any late completion attempt with expired lease returns LEASE_EXPIRED

8.2 Action failure before commit

If an exception occurs before transaction commit:

subject state remains unchanged

lease remains in previous committed state

execution record remains absent or in previous committed state

caller retries with same idempotency key

8.3 Action failure after external side effect

If external work was launched and the callback/result is uncertain:

subject remains WAITING_EXTERNAL or RUNNING

operator/admin must reconcile through explicit requeue, hold, or cancel action

no silent rollback is allowed

reconciliation must produce a new execution_record

8.4 Retry policy

Retry classification MUST be one of:

TRANSIENT_SYSTEM

TRANSIENT_DEPENDENCY

TRANSIENT_CAPACITY

PERMANENT_INPUT

PERMANENT_STATE

BUSINESS_RULE_HOLD

OPERATOR_CANCELED

Retry behavior:

transient classes -> FAILED_RETRYABLE

permanent/state/input -> FAILED_TERMINAL

business-rule hold -> HELD

operator canceled -> CANCELED

8.5 Backoff

On retryable failure:

increment subject.execution.attempt_count

compute next retry timestamp from queue retry policy

set:

state = FAILED_RETRYABLE

retry_at = computed_timestamp

next_queue_key = same queue or new queue

mark lease terminal with RELEASED

update execution record to FAILED_RETRYABLE

8.6 Max attempts and dead letter

If attempt_count >= max_attempts:

set subject state = FAILED_TERMINAL

set terminal = true

create dead_letter_record

create lineage:

subject -> dead_letter_record

queue -> dead_letter_record

execution_record -> dead_letter_record

subject is no longer visible in any queue until operator requeues it

8.7 Holds / stop-the-line

The integrity doctrine requires stop-the-line behavior and ALCOA-grade electronic footprints for integrity-critical actions. execution_hold is the queue-system implementation of that rule. Hold actions must create explicit persisted evidence, not informal flags. 

LSMC_design_principles

 

LSMC_design_principles

8.8 Failure review objects

Every terminal failure or repeated retry MUST be inspectable through:

subject execution envelope

lease history

execution record history

dead-letter record if terminal

action instance history

No hidden worker-local state is allowed.

9. Observability
9.1 Required metrics

Expose these metrics per queue and per tenant:

queue_depth

oldest_job_age_seconds

newest_job_age_seconds

active_leases

expired_leases_total

retryable_failures_total

terminal_failures_total

throughput_success_per_minute

throughput_failure_per_minute

failure_rate

dead_letter_count

held_count

worker_online_count

worker_heartbeat_lag_seconds

claim_conflict_total

idempotent_replay_total

Definitions:

queue_depth = count(visible subjects)

oldest_job_age_seconds = now - min(queue_ready_timestamp)

throughput_success_per_minute = count(execution_record.status == SUCCEEDED over window) / minutes(window)

failure_rate = failures / (successes + failures) over same window

9.2 Required read APIs

All GET endpoints are read models only.

GET /api/v1/execution/queues

returns queue summaries

GET /api/v1/execution/queues/{queue_key}

returns queue config + summary

GET /api/v1/execution/queues/{queue_key}/items

returns visible items with ordering fields

GET /api/v1/execution/subjects/{euid}

returns subject execution envelope + derived visibility reasons

GET /api/v1/execution/subjects/{euid}/history

returns execution records, holds, leases, dead letters

GET /api/v1/execution/workers

GET /api/v1/execution/workers/{worker_euid}

GET /api/v1/execution/leases?status=ACTIVE

GET /api/v1/execution/dead-letter

9.3 “Why not in queue” diagnostics

GET /api/v1/execution/subjects/{euid} MUST include computed reasons:

active hold

active lease

retry window not reached

next queue key missing

state not eligible

queue disabled

capability mismatch

cancel requested

terminal state

This is required for operator usability and for testing.

9.4 Auditability

Execution evidence must be produced during normal work, not reconstructed later. Execution history must remain explainable by lineage + records + action history. Integrity-critical actions must have electronic footprints showing who/when/what/why/version. 

LSMC_architecture_principles

 

LSMC_design_principles

9.5 Logging/tracing

Every queue action MUST log:

tenant

subject EUID

worker EUID

lease EUID

queue key

action key

idempotency key

expected state

terminal status if any

duration

If event bus/outbox exists, include correlation IDs without PHI. 

LSMC_appendix_C_domain_events_a…

10. Operator UI requirements
10.1 Required UI screens

Queue dashboard

queue depth

oldest age

active leases

held count

dead-letter count

worker coverage

Queue detail

visible items in execution order

item priority / ready time / due time / attempts

quick claim for human worker

filter by site/platform/assay/state

Subject inspector

authoritative execution envelope

derived queue visibility status

active lease

holds

execution history

lineage links to related objects

dead-letter info

Worker dashboard

online/offline/draining/disabled

last heartbeat

active lease count

current capabilities/scopes

Dead-letter / holds workbench

triage list

reason/error

requeue

cancel

release hold

10.2 Required operator actions

Operators must be able to:

view queue state

inspect any subject

place hold

release hold

requeue a subject

cancel a subject

drain/disable a worker (admin)

force-expire a lease (admin)

claim a subject as a human worker

All POST actions MUST go through TapDB action execution.

10.3 Required action endpoints

POST /api/v1/execution/actions/register-worker

POST /api/v1/execution/actions/heartbeat-worker

POST /api/v1/execution/actions/claim

POST /api/v1/execution/actions/renew-lease

POST /api/v1/execution/actions/release-lease

POST /api/v1/execution/actions/complete

POST /api/v1/execution/actions/fail

POST /api/v1/execution/actions/hold

POST /api/v1/execution/actions/release-hold

POST /api/v1/execution/actions/requeue

POST /api/v1/execution/actions/cancel

POST /api/v1/execution/actions/expire-lease (admin)

10.4 Permissions

Minimum roles:

worker_service

worker_human

operator

admin

Rules:

workers may only renew/release/complete/fail their own active leases

operators may hold/requeue/cancel

admins may force-expire leases and drain workers

11. Testing requirements

Codex MUST add automated tests for the new subsystem. Tests must cover both service-worker and human-worker flows. Use current queue flow tests as compatibility regression targets and add new tests under dedicated execution queue test modules.

11.1 Required concurrency tests

Parallel worker collision

seed one READY subject in one queue

register two workers able to service same queue

issue two concurrent claim_queue_item actions

assert exactly one active lease exists

assert only one execution record was created in STARTED

assert queue depth drops from 1 to 0

Lease expiration recovery

create subject, claim lease

advance time past expires_at

assert queue query sees subject visible again even before sweeper runs

second worker claims successfully

sweeper marks old lease EXPIRED

Worker crash recovery

worker claims and does not heartbeat

new worker later claims and completes

old worker attempting late completion receives LEASE_EXPIRED

11.2 Required idempotency tests

Retry idempotency

call fail_queue_execution twice with same idempotency_key

assert subject attempt_count increments once

assert one terminal execution record update

assert one outbox/event emission if enabled

Payload-hash conflict

repeat same idempotency_key with different payload

assert deterministic conflict

assert no mutation

Completion replay

call complete_queue_execution twice with same key

assert same response returned

no extra execution record or lease mutation

11.3 Required state/queue consistency tests

Queue/state consistency

clear or corrupt non-authoritative queue cache

assert queue visibility still follows authoritative execution envelope + lineage

assert no queue-membership edge is required

Held item removed from queue

place hold on visible subject

assert queue depth decrements

release hold and requeue

assert subject returns to queue

Cancel removes item from queue

cancel visible subject

assert queue depth decrements

assert subject becomes terminal/nonvisible

Max-attempt dead-letter

repeatedly fail retryably until max attempts reached

assert subject state becomes FAILED_TERMINAL

assert dead-letter record exists

assert no further queue visibility

11.4 Required lineage-only relationship tests

Relationships are lineage only

create queue, worker, lease, execution record

assert authoritative relationships are discoverable from lineage

assert removal of lookup metadata does not break relationship traversal

assert code never depends on JSON lookup fields as relationship truth

Lineage consistency on claim

claim action must create:

subject -> lease

worker -> lease

queue -> lease

subject -> execution_record

worker -> execution_record

queue -> execution_record

lease -> execution_record

assert all lineage links are created in one transaction

11.5 Required wet-lab and compute flow tests

Wet-lab queue chain regression

accepted specimen -> extraction -> post-extract QC -> library prep -> pooling -> run start

assert each step uses derived queue visibility and action-driven transitions

Compute execution flow

analysis request -> compute dispatch queue -> running -> artifact registration -> QC -> completed

assert same queue engine works for non-material/data subjects

Artifact/reprocessing compatibility

requeue compute subject against existing artifacts

assert lineage and execution history remain intact

assert no specimen-side workflow table is introduced

11.6 Required failure tests

Invalid transition blocked

request action with wrong expected state

assert conflict and zero mutation

Renew expired lease blocked

lease expires

renew request fails

late completion fails

Sweeper idempotency

run expire_queue_lease twice on same expired lease

second call is no-op

No hidden direct writes

existing compatibility endpoints must result in action instance creation

assert direct domain write path is not used

11.7 Required observability tests

Queue metrics correctness

seed visible, held, leased, dead-lettered, retry-pending items

assert queue_depth, held_count, active_leases, dead_letter_count, oldest_job_age are correct

Why-not-visible diagnostics

for each exclusion reason, assert subject inspector returns correct explanation

Final implementation rule

Codex MUST implement the subsystem so that:

subject state is authoritative

queue membership is derived

exclusivity is enforced by lease objects

proof is stored in execution records

all object relationships are lineage links only

all mutations happen through TapDB actions

retries, crashes, and duplicate delivery are safe by design

This keeps the execution plane fast and replaceable while preserving append-only evidence, explicit authority boundaries, and operator-visible auditability. 