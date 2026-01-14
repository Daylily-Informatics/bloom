"""
BLOOM LIMS API v1 - Batch Operations Endpoints

Endpoints for bulk processing operations.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from bloom_lims.core.batch_operations import (
    BatchProcessor,
    BatchJob,
    JobStatus,
    get_batch_processor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batch", tags=["Batch Operations"])


# Request/Response schemas
class BulkCreateRequest(BaseModel):
    """Request for bulk object creation."""
    template_euid: str = Field(..., description="Template EUID to instantiate")
    count: int = Field(..., ge=1, le=10000, description="Number of objects to create")
    name_pattern: str = Field(
        default="Object_{index}",
        description="Name pattern with {index} placeholder"
    )
    json_addl_template: Optional[Dict[str, Any]] = Field(
        None,
        description="Template for json_addl (applied to all objects)"
    )


class BulkUpdateRequest(BaseModel):
    """Request for bulk object updates."""
    updates: List[Dict[str, Any]] = Field(
        ...,
        description="List of updates with 'euid' and fields to update",
        max_length=10000,
    )


class BulkDeleteRequest(BaseModel):
    """Request for bulk object deletion."""
    euids: List[str] = Field(
        ...,
        description="List of EUIDs to delete",
        max_length=10000,
    )
    soft_delete: bool = Field(
        default=True,
        description="Soft delete (set is_deleted=True) vs hard delete"
    )


class JobResponse(BaseModel):
    """Response for batch job operations."""
    job_id: str
    operation: str
    status: str
    progress: Dict[str, Any]
    message: str


def get_bdb():
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3()


@router.post("/create", response_model=JobResponse)
async def bulk_create_objects(
    request: BulkCreateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Create multiple objects from a template.
    
    Returns immediately with a job ID for tracking progress.
    """
    try:
        bdb = get_bdb()
        processor = BatchProcessor(bdb)
        
        # Create data generator if template provided
        data_gen = None
        if request.json_addl_template:
            def data_gen(i):
                return dict(request.json_addl_template)
        
        # Start job in background
        job = processor.create_job("bulk_create", request.count)
        
        async def run_job():
            await processor.bulk_create_objects(
                template_euid=request.template_euid,
                count=request.count,
                data_generator=data_gen,
                name_pattern=request.name_pattern,
            )
        
        background_tasks.add_task(run_job)
        
        return JobResponse(
            job_id=job.job_id,
            operation="bulk_create",
            status=job.status.value,
            progress={
                "total": request.count,
                "processed": 0,
                "percent_complete": 0,
            },
            message=f"Batch create job started for {request.count} objects",
        )
        
    except Exception as e:
        logger.error(f"Error starting bulk create: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update", response_model=JobResponse)
async def bulk_update_objects(
    request: BulkUpdateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Update multiple objects by EUID.
    
    Each update dict must contain 'euid' plus fields to update.
    """
    try:
        bdb = get_bdb()
        processor = BatchProcessor(bdb)
        
        job = processor.create_job("bulk_update", len(request.updates))
        
        async def run_job():
            await processor.bulk_update_objects(request.updates)
        
        background_tasks.add_task(run_job)
        
        return JobResponse(
            job_id=job.job_id,
            operation="bulk_update",
            status=job.status.value,
            progress={
                "total": len(request.updates),
                "processed": 0,
                "percent_complete": 0,
            },
            message=f"Batch update job started for {len(request.updates)} objects",
        )
        
    except Exception as e:
        logger.error(f"Error starting bulk update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete", response_model=JobResponse)
async def bulk_delete_objects(
    request: BulkDeleteRequest,
    background_tasks: BackgroundTasks,
):
    """
    Delete multiple objects by EUID.

    By default performs soft delete (sets is_deleted=True).
    """
    try:
        bdb = get_bdb()
        processor = BatchProcessor(bdb)

        job = processor.create_job("bulk_delete", len(request.euids))

        async def run_job():
            await processor.bulk_delete_objects(
                euids=request.euids,
                soft_delete=request.soft_delete,
            )

        background_tasks.add_task(run_job)

        return JobResponse(
            job_id=job.job_id,
            operation="bulk_delete",
            status=job.status.value,
            progress={
                "total": len(request.euids),
                "processed": 0,
                "percent_complete": 0,
            },
            message=f"Batch delete job started for {len(request.euids)} objects",
        )

    except Exception as e:
        logger.error(f"Error starting bulk delete: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs", response_model=Dict[str, Any])
async def list_batch_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=1000),
):
    """List all batch jobs with optional status filter."""
    try:
        processor = get_batch_processor()
        jobs = processor.get_all_jobs()

        if status:
            jobs = [j for j in jobs if j.status.value == status]

        return {
            "jobs": [j.to_dict() for j in jobs[-limit:]],
            "total": len(jobs),
        }

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=Dict[str, Any])
async def get_batch_job(job_id: str):
    """Get batch job status and progress."""
    try:
        processor = get_batch_processor()
        job = processor.get_job(job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

        response = job.to_dict()

        # Include results/errors for completed jobs
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            response["results"] = job.results[:100]  # Limit for response size
            response["errors"] = job.errors[:100]

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/cancel")
async def cancel_batch_job(job_id: str):
    """Request cancellation of a running batch job."""
    try:
        processor = get_batch_processor()

        if processor.cancel_job(job_id):
            return {"success": True, "message": f"Cancellation requested for job {job_id}"}
        else:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

