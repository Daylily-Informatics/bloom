"""
BLOOM LIMS API v1 - Async Task Endpoints

Endpoints for submitting and managing async background tasks.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from bloom_lims.core.async_operations import (
    BackgroundTaskManager,
    TaskResult,
    TaskStatus,
    get_task_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["Async Tasks"])


# Request/Response schemas
class TaskSubmitRequest(BaseModel):
    """Request to submit a predefined async task."""
    task_type: str = Field(..., description="Type of task to run")
    params: Dict[str, Any] = Field(default={}, description="Task parameters")
    callback_url: Optional[str] = Field(None, description="Webhook URL for completion callback")


class TaskResponse(BaseModel):
    """Response for task operations."""
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """Detailed task status response."""
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


# Predefined task registry
TASK_REGISTRY: Dict[str, Any] = {}


def register_task(name: str):
    """Decorator to register a task function."""
    def decorator(func):
        TASK_REGISTRY[name] = func
        return func
    return decorator


# Example registered tasks
@register_task("echo")
async def echo_task(message: str = "Hello") -> str:
    """Simple echo task for testing."""
    import asyncio
    await asyncio.sleep(1)  # Simulate work
    return f"Echo: {message}"


@register_task("process_data")
async def process_data_task(data: List[Any], operation: str = "count") -> Dict[str, Any]:
    """Process data with specified operation."""
    import asyncio
    await asyncio.sleep(0.1 * len(data))  # Simulate processing time
    
    if operation == "count":
        return {"count": len(data)}
    elif operation == "sum":
        return {"sum": sum(data) if all(isinstance(x, (int, float)) for x in data) else 0}
    else:
        return {"data": data, "operation": operation}


@router.post("/submit", response_model=TaskResponse)
async def submit_task(request: TaskSubmitRequest):
    """
    Submit a predefined task for async execution.
    
    Available task types can be queried via GET /tasks/types.
    """
    try:
        if request.task_type not in TASK_REGISTRY:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown task type: {request.task_type}. Use GET /tasks/types for available tasks."
            )
        
        task_func = TASK_REGISTRY[request.task_type]
        manager = get_task_manager()
        
        task_id = await manager.submit(task_func, **request.params)
        
        return TaskResponse(
            task_id=task_id,
            status="pending",
            message=f"Task {request.task_type} submitted successfully",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types", response_model=Dict[str, Any])
async def list_task_types():
    """List available task types and their descriptions."""
    return {
        "task_types": [
            {
                "name": name,
                "description": func.__doc__ or "No description",
            }
            for name, func in TASK_REGISTRY.items()
        ]
    }


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get status of a submitted task."""
    try:
        manager = get_task_manager()
        result = await manager.get_status(task_id)
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        
        return TaskStatusResponse(
            task_id=result.task_id,
            status=result.status.value,
            result=result.result if result.status == TaskStatus.COMPLETED else None,
            error=result.error,
            started_at=result.started_at.isoformat() if result.started_at else None,
            completed_at=result.completed_at.isoformat() if result.completed_at else None,
            duration_seconds=result.duration_seconds,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/wait", response_model=TaskStatusResponse)
async def wait_for_task(
    task_id: str,
    timeout: float = Query(30, ge=1, le=300, description="Max seconds to wait"),
):
    """
    Wait for a task to complete and return the result.

    Will return immediately if task is already complete.
    """
    try:
        import asyncio

        manager = get_task_manager()

        try:
            result = await manager.get_result(task_id, timeout=timeout)
        except asyncio.TimeoutError:
            result = await manager.get_status(task_id)
            if not result:
                raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

        return TaskStatusResponse(
            task_id=result.task_id,
            status=result.status.value,
            result=result.result if result.status == TaskStatus.COMPLETED else None,
            error=result.error,
            started_at=result.started_at.isoformat() if result.started_at else None,
            completed_at=result.completed_at.isoformat() if result.completed_at else None,
            duration_seconds=result.duration_seconds,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error waiting for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a pending or running task."""
    try:
        manager = get_task_manager()

        if await manager.cancel(task_id):
            return {"success": True, "message": f"Task {task_id} cancelled"}
        else:
            raise HTTPException(status_code=404, detail=f"Task not found or already complete: {task_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=Dict[str, Any])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=1000),
):
    """List all tasks with optional status filter."""
    try:
        manager = get_task_manager()
        all_tasks = manager.get_all_tasks()

        tasks = []
        for task_id, result in all_tasks.items():
            if status and result.status.value != status:
                continue
            tasks.append({
                "task_id": task_id,
                "status": result.status.value,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            })

        return {
            "tasks": tasks[-limit:],
            "total": len(tasks),
            "stats": manager.get_stats(),
        }

    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

