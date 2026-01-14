"""
BLOOM LIMS Batch Operations

Provides bulk processing capabilities for high-throughput operations.

Usage:
    from bloom_lims.core.batch_operations import (
        BatchProcessor,
        BatchJob,
        bulk_create,
        bulk_update,
        bulk_delete,
    )
    
    # Batch processing with progress tracking
    processor = BatchProcessor(bdb)
    job = await processor.create_objects(
        template_euid="CT123",
        count=1000,
        data_generator=lambda i: {"name": f"Sample_{i}"},
    )
    
    # Check progress
    status = processor.get_job_status(job.job_id)
    
    # Bulk operations
    results = await bulk_create(session, objects_data)
    updated = await bulk_update(session, updates)

Features:
    - Batched database operations for efficiency
    - Progress tracking for long-running jobs
    - Automatic chunking to prevent memory issues
    - Transaction management with rollback support
    - Parallel processing options
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional, TypeVar, Union

from sqlalchemy import text, update, delete
from sqlalchemy.orm import Session

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class JobStatus(str, Enum):
    """Status of a batch job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class BatchProgress:
    """Progress tracking for batch operations."""
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    
    @property
    def percent_complete(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100
    
    @property
    def remaining(self) -> int:
        return self.total - self.processed


@dataclass
class BatchJob:
    """Represents a batch processing job."""
    job_id: str
    operation: str
    status: JobStatus = JobStatus.PENDING
    progress: BatchProgress = field(default_factory=BatchProgress)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "operation": self.operation,
            "status": self.status.value,
            "progress": {
                "total": self.progress.total,
                "processed": self.progress.processed,
                "succeeded": self.progress.succeeded,
                "failed": self.progress.failed,
                "skipped": self.progress.skipped,
                "percent_complete": round(self.progress.percent_complete, 2),
            },
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "result_count": len(self.results),
            "error_count": len(self.errors),
        }


class BatchProcessor:
    """
    Processor for batch database operations.
    
    Handles bulk creates, updates, and deletes with progress tracking.
    """
    
    def __init__(
        self,
        bdb,
        chunk_size: int = 100,
        max_concurrent: int = 5,
    ):
        """
        Initialize batch processor.
        
        Args:
            bdb: BLOOMdb3 database instance
            chunk_size: Number of items per batch
            max_concurrent: Maximum concurrent operations
        """
        self._bdb = bdb
        self._session = bdb.session
        self._Base = bdb.Base
        self.chunk_size = chunk_size
        self.max_concurrent = max_concurrent
        self._jobs: Dict[str, BatchJob] = {}
        self._cancel_flags: Dict[str, bool] = {}
    
    def _chunks(self, items: List[T], size: int) -> Generator[List[T], None, None]:
        """Split list into chunks."""
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def create_job(self, operation: str, total: int) -> BatchJob:
        """Create a new batch job."""
        job = BatchJob(
            job_id=str(uuid.uuid4()),
            operation=operation,
            progress=BatchProgress(total=total),
        )
        self._jobs[job.job_id] = job
        self._cancel_flags[job.job_id] = False
        return job

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Request job cancellation."""
        if job_id in self._cancel_flags:
            self._cancel_flags[job_id] = True
            return True
        return False

    def _is_cancelled(self, job_id: str) -> bool:
        """Check if job is cancelled."""
        return self._cancel_flags.get(job_id, False)

    async def bulk_create_objects(
        self,
        template_euid: str,
        count: int,
        data_generator: Optional[Callable[[int], Dict[str, Any]]] = None,
        name_pattern: str = "Object_{index}",
    ) -> BatchJob:
        """
        Create multiple objects from a template.

        Args:
            template_euid: Template EUID to instantiate
            count: Number of objects to create
            data_generator: Optional function to generate json_addl for each object
            name_pattern: Name pattern with {index} placeholder

        Returns:
            BatchJob with created object EUIDs
        """
        job = self.create_job("bulk_create", count)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()

        try:
            # Get template
            template = (
                self._session.query(self._Base.classes.generic_template)
                .filter(self._Base.classes.generic_template.euid == template_euid)
                .first()
            )

            if not template:
                raise ValueError(f"Template not found: {template_euid}")

            # Process in chunks
            for chunk_start in range(0, count, self.chunk_size):
                if self._is_cancelled(job.job_id):
                    job.status = JobStatus.CANCELLED
                    break

                chunk_end = min(chunk_start + self.chunk_size, count)

                for i in range(chunk_start, chunk_end):
                    try:
                        # Generate object data
                        name = name_pattern.format(index=i + 1)
                        json_addl = data_generator(i) if data_generator else {}

                        # Create instance
                        instance_class = getattr(self._Base.classes, 'generic_instance')
                        instance = instance_class(
                            name=name,
                            btype=template.btype,
                            b_sub_type=template.b_sub_type,
                            super_type=template.super_type,
                            json_addl=json_addl,
                            parent_template_uuid=template.uuid,
                        )
                        self._session.add(instance)

                        job.progress.succeeded += 1
                        job.results.append({"index": i, "name": name})

                    except Exception as e:
                        job.progress.failed += 1
                        job.errors.append({"index": i, "error": str(e)})
                        logger.warning(f"Failed to create object {i}: {e}")

                    job.progress.processed += 1

                # Commit chunk
                self._session.commit()
                logger.debug(f"Committed chunk {chunk_start}-{chunk_end}")

            job.status = JobStatus.COMPLETED

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            self._session.rollback()
            logger.error(f"Batch create failed: {e}")

        job.completed_at = datetime.utcnow()
        return job

    async def bulk_update_objects(
        self,
        updates: List[Dict[str, Any]],
    ) -> BatchJob:
        """
        Update multiple objects by EUID.

        Args:
            updates: List of dicts with 'euid' and fields to update

        Returns:
            BatchJob with update results
        """
        job = self.create_job("bulk_update", len(updates))
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()

        try:
            for chunk in self._chunks(updates, self.chunk_size):
                if self._is_cancelled(job.job_id):
                    job.status = JobStatus.CANCELLED
                    break

                for item in chunk:
                    euid = item.get('euid')
                    if not euid:
                        job.progress.skipped += 1
                        job.progress.processed += 1
                        continue

                    try:
                        obj = (
                            self._session.query(self._Base.classes.generic_instance)
                            .filter(self._Base.classes.generic_instance.euid == euid)
                            .first()
                        )

                        if obj:
                            for key, value in item.items():
                                if key != 'euid' and hasattr(obj, key):
                                    setattr(obj, key, value)

                            job.progress.succeeded += 1
                            job.results.append({"euid": euid, "status": "updated"})
                        else:
                            job.progress.skipped += 1
                            job.errors.append({"euid": euid, "error": "not_found"})

                    except Exception as e:
                        job.progress.failed += 1
                        job.errors.append({"euid": euid, "error": str(e)})

                    job.progress.processed += 1

                self._session.commit()

            job.status = JobStatus.COMPLETED

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            self._session.rollback()

        job.completed_at = datetime.utcnow()
        return job

    async def bulk_delete_objects(
        self,
        euids: List[str],
        soft_delete: bool = True,
    ) -> BatchJob:
        """
        Delete multiple objects by EUID.

        Args:
            euids: List of EUIDs to delete
            soft_delete: If True, set is_deleted=True; if False, hard delete

        Returns:
            BatchJob with deletion results
        """
        job = self.create_job("bulk_delete", len(euids))
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()

        try:
            for chunk in self._chunks(euids, self.chunk_size):
                if self._is_cancelled(job.job_id):
                    job.status = JobStatus.CANCELLED
                    break

                for euid in chunk:
                    try:
                        obj = (
                            self._session.query(self._Base.classes.generic_instance)
                            .filter(self._Base.classes.generic_instance.euid == euid)
                            .first()
                        )

                        if obj:
                            if soft_delete:
                                obj.is_deleted = True
                            else:
                                self._session.delete(obj)

                            job.progress.succeeded += 1
                            job.results.append({"euid": euid, "status": "deleted"})
                        else:
                            job.progress.skipped += 1

                    except Exception as e:
                        job.progress.failed += 1
                        job.errors.append({"euid": euid, "error": str(e)})

                    job.progress.processed += 1

                self._session.commit()

            job.status = JobStatus.COMPLETED

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            self._session.rollback()

        job.completed_at = datetime.utcnow()
        return job

    def get_all_jobs(self) -> List[BatchJob]:
        """Get all batch jobs."""
        return list(self._jobs.values())

    def cleanup_completed_jobs(self, max_age_hours: int = 24) -> int:
        """Remove old completed jobs."""
        cutoff = datetime.utcnow()
        removed = 0

        to_remove = []
        for job_id, job in self._jobs.items():
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                if job.completed_at:
                    age_hours = (cutoff - job.completed_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        to_remove.append(job_id)

        for job_id in to_remove:
            del self._jobs[job_id]
            if job_id in self._cancel_flags:
                del self._cancel_flags[job_id]
            removed += 1

        return removed


# Convenience functions for simple bulk operations
async def bulk_create(
    session: Session,
    model_class,
    items: List[Dict[str, Any]],
    chunk_size: int = 100,
) -> Dict[str, Any]:
    """
    Bulk create objects directly.

    Args:
        session: SQLAlchemy session
        model_class: ORM model class
        items: List of dictionaries with object data
        chunk_size: Items per transaction chunk

    Returns:
        Summary dict with counts and any errors
    """
    results = {"created": 0, "failed": 0, "errors": []}

    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]

        try:
            for item in chunk:
                obj = model_class(**item)
                session.add(obj)
                results["created"] += 1

            session.commit()
        except Exception as e:
            session.rollback()
            results["failed"] += len(chunk)
            results["errors"].append({"chunk": i // chunk_size, "error": str(e)})

    return results


async def bulk_update(
    session: Session,
    model_class,
    updates: List[Dict[str, Any]],
    id_field: str = "euid",
    chunk_size: int = 100,
) -> Dict[str, Any]:
    """
    Bulk update objects directly.

    Args:
        session: SQLAlchemy session
        model_class: ORM model class
        updates: List of dicts with id_field and fields to update
        id_field: Field name used for lookup
        chunk_size: Items per transaction chunk

    Returns:
        Summary dict with counts
    """
    results = {"updated": 0, "not_found": 0, "failed": 0, "errors": []}

    for i in range(0, len(updates), chunk_size):
        chunk = updates[i:i + chunk_size]

        try:
            for item in chunk:
                id_value = item.get(id_field)
                if not id_value:
                    continue

                obj = session.query(model_class).filter(
                    getattr(model_class, id_field) == id_value
                ).first()

                if obj:
                    for key, value in item.items():
                        if key != id_field and hasattr(obj, key):
                            setattr(obj, key, value)
                    results["updated"] += 1
                else:
                    results["not_found"] += 1

            session.commit()
        except Exception as e:
            session.rollback()
            results["failed"] += len(chunk)
            results["errors"].append({"chunk": i // chunk_size, "error": str(e)})

    return results


async def bulk_delete(
    session: Session,
    model_class,
    ids: List[Any],
    id_field: str = "euid",
    soft_delete: bool = True,
    chunk_size: int = 100,
) -> Dict[str, Any]:
    """
    Bulk delete objects directly.

    Args:
        session: SQLAlchemy session
        model_class: ORM model class
        ids: List of ID values to delete
        id_field: Field name used for lookup
        soft_delete: Set is_deleted=True vs hard delete
        chunk_size: Items per transaction chunk

    Returns:
        Summary dict with counts
    """
    results = {"deleted": 0, "not_found": 0, "failed": 0, "errors": []}

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]

        try:
            for id_value in chunk:
                obj = session.query(model_class).filter(
                    getattr(model_class, id_field) == id_value
                ).first()

                if obj:
                    if soft_delete and hasattr(obj, 'is_deleted'):
                        obj.is_deleted = True
                    else:
                        session.delete(obj)
                    results["deleted"] += 1
                else:
                    results["not_found"] += 1

            session.commit()
        except Exception as e:
            session.rollback()
            results["failed"] += len(chunk)
            results["errors"].append({"chunk": i // chunk_size, "error": str(e)})

    return results


# Global processor instance
_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor(bdb=None) -> BatchProcessor:
    """
    Get batch processor singleton.

    Args:
        bdb: Optional BLOOMdb3 instance (creates new if not provided)
    """
    global _batch_processor

    if _batch_processor is None or bdb is not None:
        if bdb is None:
            from bloom_lims.db import BLOOMdb3
            bdb = BLOOMdb3()

        settings = get_settings()
        _batch_processor = BatchProcessor(
            bdb,
            chunk_size=getattr(settings.api, 'batch_chunk_size', 100),
            max_concurrent=getattr(settings.api, 'batch_max_concurrent', 5),
        )

    return _batch_processor

