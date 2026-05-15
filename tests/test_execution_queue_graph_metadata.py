"""Focused coverage for execution queue graph metadata."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from bloom_lims.domain.execution_queue import ExecutionQueueService


def _service_without_db() -> ExecutionQueueService:
    return object.__new__(ExecutionQueueService)


def test_default_execution_queue_graph_metadata_bounds_persistent_fanout() -> None:
    service = _service_without_db()

    defaults = service._queue_definition_defaults(
        "ilmn_start_seq_run",
        ExecutionQueueService.WETLAB_QUEUE_DEFAULTS["ilmn_start_seq_run"],
    )

    graph = defaults["graph"]
    assert graph["node_role"] == "execution_queue"
    assert graph["role"] == "bloom_execution_queue"
    assert graph["expected_fanout_max"] >= 200
    assert "persistent execution queues" in graph["fanout_reason"]

    [fanout] = graph["expected_fanout"]
    assert fanout["scope"] == "same_service"
    assert fanout["relationship_types"] == [
        ExecutionQueueService.REL_QUEUE_LEASE,
        ExecutionQueueService.REL_QUEUE_RECORD,
    ]
    assert fanout["max_child_count"] == graph["expected_fanout_max"]


def test_ensure_default_queue_definitions_refreshes_existing_queue_graph() -> None:
    service = _service_without_db()
    service.WETLAB_QUEUE_DEFAULTS = {
        "ilmn_start_seq_run": ExecutionQueueService.WETLAB_QUEUE_DEFAULTS[
            "ilmn_start_seq_run"
        ]
    }
    existing_queue = SimpleNamespace(
        name="stale queue",
        json_addl={
            "properties": {
                "queue_key": "ilmn_start_seq_run",
                "display_name": "Stale Queue",
                "revision": 7,
                "graph": {
                    "node_role": "execution_queue",
                    "expected_fanout_max": 10,
                    "expected_fanout": [
                        {
                            "relationship_types": [
                                ExecutionQueueService.REL_QUEUE_LEASE,
                                ExecutionQueueService.REL_QUEUE_RECORD,
                            ],
                            "max_child_count": 10,
                        }
                    ],
                },
            }
        },
    )
    session = SimpleNamespace(flush_count=0)

    def flush() -> None:
        session.flush_count += 1

    session.flush = flush
    service.bdb = SimpleNamespace(session=session)
    service._find_queue_by_key = lambda queue_key: existing_queue

    def write_props(instance, props) -> None:
        instance.json_addl = {"properties": deepcopy(props)}

    service._write_props = write_props

    service.ensure_default_queue_definitions()

    props = existing_queue.json_addl["properties"]
    graph = props["graph"]
    assert existing_queue.name == "Illumina Start Run"
    assert props["name"] == "Illumina Start Run"
    assert props["revision"] == 8
    assert graph["expected_fanout_max"] >= 200
    assert graph["expected_fanout"][0]["max_child_count"] == graph["expected_fanout_max"]
    assert session.flush_count == 1
