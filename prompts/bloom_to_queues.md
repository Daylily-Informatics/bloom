Below is a queue-driven Bloom architecture I’d actually build for your use case: “Bloom is a clean biospecimen container system + lab work queues,” with no workflow/workflow_step engine. Everything is driven by material state + queues + operations.

Assumptions and trade-offs

Assumption: Bloom is the system of record for physical material and lab execution state.

Assumption: Atlas owns TRF/orders/tests and asks Bloom for material status.

Trade-off: You lose “generic configurable workflow steps,” but gain the thing labs actually run on: queues and operations that can change without a schema rewrite.

Core concepts

Material objects

Container (tube)

Specimen (material inside a container)

Aliquot (derived portion)

Plate + PlateWell (physical placements)

Queues

Named bins of work waiting to be done, by assay or station.

Queue membership is explicit and queryable.

Operations

The only thing that changes state.

Operations consume queue items and produce state changes and artifacts (plates, aliquots), plus audit records.

State

Material state is tracked per object (container/specimen/aliquot), plus queue membership.

Data model
1) Canonical enums

object_type: container | specimen | aliquot | plate | plate_well

queue_type: intake | accessioned | extraction | library_prep | assay_hla | assay_carrier | platefill | qc | hold | exception | archive

material_state: minimal and operational, not “workflow-step”

Containers: registered | received | assigned | consumed | retired

Specimens: created | accessioned | queued | in_process | blocked | completed | retired

Aliquots: created | queued | in_process | completed | consumed | retired

op_type: receive_container | derive_specimen | split_aliquot | move_queue | qc_check | platefill | consume | retire | annotate

Keep these enums small. Anything more detailed belongs in attributes (JSON) so you can evolve without migrations.

2) Tables (Postgres)
container

container_euid (PK)

barcode (unique, nullable until scanned)

container_type (tube type)

state (container_state enum)

received_at (nullable)

attributes (jsonb)
Examples: volume, anticoagulant, collection_time, temperature, notes

Indexes

unique(barcode)

(state)

(received_at)

specimen

specimen_euid (PK)

container_euid (FK container)

specimen_type (blood, dna, plasma, etc)

state (specimen_state enum)

attributes (jsonb)
Examples: yield_ng, concentration_ng_ul, extraction_method, qc_metrics

Indexes

(container_euid)

(state)

aliquot

aliquot_euid (PK)

parent_object_type (specimen or aliquot)

parent_euid

state (aliquot_state enum)

attributes (jsonb)

Indexes

(parent_object_type, parent_euid)

(state)

plate

plate_euid (PK)

plate_type (96, 384)

assay_type (hla, carrier, etc)

state (plate_state: created, filled, sealed, in_process, completed, archived)

attributes (jsonb)

plate_well

plate_well_euid (PK)

plate_euid (FK plate)

well (A01..H12)

object_type (specimen/aliquot)

object_euid

state (assigned, filled, consumed)

attributes (jsonb)

Indexes

unique(plate_euid, well)

(object_type, object_euid)

3) Queue system
queue

queue_id (PK)

name (unique)

queue_type (enum)

assay_type (nullable)

station (nullable, string)

capacity (nullable int)

attributes (jsonb)
Examples: SLA, priority weights, required qc thresholds

queue_item

Represents membership of a material object in a queue.

queue_item_id (PK)

queue_id (FK)

object_type

object_euid

status (enqueued | leased | completed | cancelled)

priority (int)

enqueued_at

leased_at (nullable)

lease_owner (nullable)

lease_expires_at (nullable)

completed_at (nullable)

attributes (jsonb)
Examples: reason, routing hint, batch_id

Indexes

unique(queue_id, object_type, object_euid) where status in (enqueued, leased)

(queue_id, status, priority desc, enqueued_at)

(object_type, object_euid, status)

This “lease” model prevents two stations from pulling the same item concurrently.

4) Operations and audit
operation

Immutable record of “what happened.”

op_id (PK)

op_type (enum)

actor_type (human | system)

actor_id (user/service)

occurred_at

idempotency_key (unique, nullable but recommended for API)

inputs (jsonb)

outputs (jsonb)

notes (text, nullable)

Indexes

unique(idempotency_key)

(occurred_at)

object_event

Per-object event stream for debugging and evidence.

event_id (PK)

object_type

object_euid

op_id (FK operation)

event_type (string)

from_state (nullable)

to_state (nullable)

from_queue_id (nullable)

to_queue_id (nullable)

payload (jsonb)

occurred_at

Indexes

(object_type, object_euid, occurred_at)

(op_id)

If you already have TapDB as an evidence ledger, Bloom can write both:

local operational log (fast reads)

TapDB ledger (compliance plane)

5) Atlas linkage (critical)

Bloom must allow Atlas to ask: “What tubes belong to this order?” without Bloom knowing orders.

Use an external reference table.

external_reference

ref_id (PK)

namespace (string)
Example: atlas.test_order

external_id (string)
Example: Atlas TestOrder EUID/UUID

object_type

object_euid

role (string)
Example: primary_tube | backup_tube | specimen | aliquot

created_at

unique(namespace, external_id, object_type, object_euid, role)

This gives Atlas a stable way to map orders to tubes/specimens without polluting Bloom’s domain.

APIs

Design principle: Bloom exposes material lifecycle + queue operations, nothing clinical.

Material APIs

Containers

POST /v1/containers

body: container_type, optional barcode, attributes

returns: container_euid

POST /v1/containers/{container_euid}/receive

sets received_at, state transition, may enqueue to intake or accessioned

GET /v1/containers/{container_euid}

GET /v1/containers?barcode=...

Specimens

POST /v1/specimens

body: container_euid, specimen_type, attributes

returns: specimen_euid

GET /v1/specimens/{specimen_euid}

Aliquots

POST /v1/aliquots

body: parent_object_type, parent_euid, attributes

returns: aliquot_euid

GET /v1/aliquots/{aliquot_euid}

Plates

POST /v1/plates

POST /v1/plates/{plate_euid}/wells/assign

GET /v1/plates/{plate_euid}

Queue APIs

Queue inspection

GET /v1/queues

GET /v1/queues/{queue_id}

GET /v1/queues/{queue_id}/items?status=enqueued

Enqueue

POST /v1/queues/{queue_id}/enqueue

body: object_type, object_euid, priority, attributes, idempotency_key

Lease (pull work)

POST /v1/queues/{queue_id}/lease

body: lease_owner, max_items, lease_ttl_seconds, filters(optional)

returns: queue_items

POST /v1/queues/items/{queue_item_id}/complete

POST /v1/queues/items/{queue_item_id}/cancel

This is the operational heart. Stations or services lease work, do it, complete it.

External reference APIs (Atlas integration)

POST /v1/external-references

body: namespace, external_id, object_type, object_euid, role

GET /v1/external-references?namespace=...&external_id=...

returns objects (tubes/specimens/aliquots) linked to that external id

State summary APIs (what Atlas wants)

GET /v1/order-material-state?namespace=atlas.test_order&external_id=...

Returns:

linked tubes/specimens

current queues

material states

plate assignment if any

qc summary fields

This keeps Atlas logic simple: compute test status from material status.

Operations model

Operations are where you should be strict. Each operation:

validates preconditions

writes an operation record

updates objects and queue_items in one transaction

writes object_event records (and optionally emits TapDB events)

Key operations

receive_container

pre: container exists, not already received

effects: container.state registered -> received, set received_at

optional: enqueue to intake queue

derive_specimen

pre: container.state is received

effects: create specimen, specimen.state created, container.state assigned or remains received depending on your semantics

optional: enqueue specimen to accessioned or extraction

move_queue (generic routing)

pre: object exists

effects: enqueue object into target queue, optionally close prior queue_item

note: routing logic can live in a rule engine later, but start explicit

qc_check

pre: specimen has required metrics in attributes

effects: set specimen.state to blocked or queued

optional: move to qc queue or back to prior

platefill

pre: N items leased from platefill queue, all compatible (assay_type, plate_type, etc.)

effects:

create plate

assign plate_wells

update specimen/aliquot state queued -> in_process or plated

complete the queue_items

consume / retire

used for irreversible steps and cleanup

Routing rules

Do not hardcode a workflow graph. Use simple routing rules:

Routing is decided by:

assay_type (from Atlas linkage role or from specimen attributes)

specimen_type

qc metrics

lab station availability

Start with explicit API calls:

Atlas or a lab service enqueues items into queues.

Later you can add a router service that watches events and enqueues accordingly, but do not block on it.

Diagrams (Mermaid)
Plane view
Core queue lifecycle
Specimen state (minimal, practical)
End-to-end lab movement
What replaces workflow/workflow_step

Replace:

workflow definitions

step definitions

step transitions

“what is the next step?”

With:

material state enums (small)

queues as the source of truth for “what needs doing”

operations as the only state-transition mechanism

optional routing service later (not required at first)

This will feel like a queue-based lab, because it is one.

Implementation notes I’d enforce

Every mutating endpoint requires idempotency_key.

Every operation writes operation + object_event in the same transaction.

Queue leasing is required for any “work pulling” endpoint.

No queue mutation without an operation record.

Bloom never stores patient, TRF, order, test_order fields. Only external references.