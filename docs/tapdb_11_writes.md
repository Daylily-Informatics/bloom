# Bloom TapDB 11 writer contract

Bloom pins `daylily-tapdb[aurora,gui]==11.0.1` with a narrow TapDB lock update.
Existing per-transaction attribution, verified human issuer/subject, native
external-reference source/lineage revision preconditions and request-owned session
cleanup remain in place.

The following existing API writers now invoke the same `require_write` dependency
as ordinary object writes, before they create database handles or dispatch work:

- POST `/api/v1/batch/create`, `/api/v1/batch/update`, `/api/v1/batch/delete`
- POST `/api/v1/equipment/`, `/api/v1/equipment/{euid}/maintenance`

Callers must use an existing verified browser session or supported bearer credential
with Bloom write permission. No role or credential is synthesized. Batch response
background tasks retain the request identity and request-owned database lifetime.
No first-party runtime HTTP callers of these five routes were found in the source
review; external callers must already supply supported authentication.

Generic detached tasks snapshot the submitting initiator. Synchronous executor
jobs install that snapshot in their own identity scope and reset it afterward, so
reused threads cannot retain a previous actor. This is not authority to add jobs.

Focused identity/route checks are authored but were not run. Native database
adoption, deployment, runtime observations and Atlas/Bloom feature acceptance
remain separate gates.

## Native mutation revisions

The service session installs an observed-revision guard for persisted instances,
lineages and service-owned templates, including queued hard deletes. Original
native revisions are retained by table/UID from the first ORM load, even if DTO
conversion releases the ORM object and it is later loaded again. Native locking
snapshots all pending column proposals before refresh; every expected revision
must match before any proposal is restored. ORM bulk update/delete bypasses are
rejected for these tables. Database ownership and integrity rules still apply.

Only a successful flush advances observations for its own changed rows. Explicit
refresh and a second lookup never silently replace an earlier expectation.
Rollback restores observations preceding that transaction's own flushes. A CAS
conflict rolls back and fences the session and current request from any later
commit; reconciliation requires a fresh request/session and a new proposal.
The actual request-local conflict yields HTTP 409 even if a legacy handler catches
and translates the exception. The conflict signal resets after the request.

DTO writers that cross sessions must carry `record_revision` and bind the original
value with `expect_revision`; a newly loaded mutation row is not the expected
version. Token-state DTOs carry this value explicitly. Authored offline checks
cover stale proposals, refresh preservation, repeated flushes, rollback restoration,
DTO expectations and request conflict isolation; they have not been executed.

Bloom batch writers accept only native mutable object fields (`name`, `bstatus`,
`json_addl`, `is_deleted`); clients cannot assign revision or identity columns.
Background batch conflicts stop the job as FAILED with `error_code: 409`, preserving
the same job ID returned by admission. Job status uses a shared process-local
receipt registry without retaining database sessions. These receipts are memory
only: they do not survive restart or synchronize across web-worker processes.
Earlier successfully committed chunks remain committed; the conflicting chunk
rolls back and is not retried. The initial background-admission response cannot
change after it has been sent; inspect its job receipt for the final outcome.
