"""
BLOOM LIMS Async Operations

Provides non-blocking async operations for high-throughput automation workflows.

Usage:
    from bloom_lims.core.async_operations import (
        AsyncDatabaseSession,
        async_query,
        async_bulk_insert,
        BackgroundTaskManager,
    )
    
    # Async database operations
    async with AsyncDatabaseSession() as session:
        results = await async_query(session, Model, filters={...})
    
    # Background tasks
    task_manager = BackgroundTaskManager()
    task_id = await task_manager.submit(my_async_func, arg1, arg2)
    result = await task_manager.get_result(task_id)

Features:
    - Async SQLAlchemy session management
    - Non-blocking database queries
    - Background task execution
    - Task status tracking and result retrieval
    - Configurable worker pools
"""

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskStatus(str, Enum):
    """Status of a background task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult(Generic[T]):
    """Result of a background task."""
    task_id: str
    status: TaskStatus
    result: Optional[T] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get task duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class AsyncDatabaseSession:
    """
    Async database session manager for non-blocking operations.
    
    Uses SQLAlchemy's async support with asyncpg driver.
    """
    
    _engine = None
    _session_factory = None
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        echo: bool = False,
    ):
        """
        Initialize async database session.
        
        Args:
            connection_string: Async database URL (postgresql+asyncpg://...)
            pool_size: Connection pool size
            max_overflow: Max connections above pool_size
            echo: Log SQL statements
        """
        settings = get_settings()
        
        if connection_string is None:
            connection_string = settings.database.async_connection_string
        
        self._create_engine_if_needed(
            connection_string,
            pool_size,
            max_overflow,
            echo,
        )
    
    @classmethod
    def _create_engine_if_needed(
        cls,
        connection_string: str,
        pool_size: int,
        max_overflow: int,
        echo: bool,
    ):
        """Create async engine singleton."""
        if cls._engine is None:
            cls._engine = create_async_engine(
                connection_string,
                pool_size=pool_size,
                max_overflow=max_overflow,
                echo=echo,
                pool_pre_ping=True,
            )
            cls._session_factory = async_sessionmaker(
                cls._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            logger.info("Created async database engine")
    
    @asynccontextmanager
    async def session(self):
        """Get an async session context."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    async def execute(self, query: str, params: Optional[Dict] = None) -> Any:
        """Execute a raw SQL query."""
        async with self.session() as session:
            result = await session.execute(text(query), params or {})
            return result
    
    @classmethod
    async def close(cls):
        """Close the async engine."""
        if cls._engine:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None
            logger.info("Closed async database engine")


class BackgroundTaskManager:
    """
    Manager for background task execution with status tracking.

    Supports both async coroutines and sync functions (run in thread pool).
    """

    def __init__(
        self,
        max_workers: int = 10,
        max_tasks: int = 1000,
    ):
        """
        Initialize task manager.

        Args:
            max_workers: Maximum concurrent workers for sync tasks
            max_tasks: Maximum number of task results to keep
        """
        self.max_workers = max_workers
        self.max_tasks = max_tasks
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: Dict[str, TaskResult] = {}
        self._pending_futures: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        func: Callable,
        *args,
        task_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Submit a task for background execution.

        Args:
            func: Async or sync callable to execute
            *args: Positional arguments for func
            task_id: Optional custom task ID
            **kwargs: Keyword arguments for func

        Returns:
            Task ID for tracking
        """
        task_id = task_id or str(uuid.uuid4())

        async with self._lock:
            # Cleanup old tasks if at capacity
            await self._cleanup_old_tasks()

            # Initialize task result
            self._tasks[task_id] = TaskResult(
                task_id=task_id,
                status=TaskStatus.PENDING,
            )

        # Create and schedule the task
        if asyncio.iscoroutinefunction(func):
            task = asyncio.create_task(
                self._run_async_task(task_id, func, *args, **kwargs)
            )
        else:
            task = asyncio.create_task(
                self._run_sync_task(task_id, func, *args, **kwargs)
            )

        self._pending_futures[task_id] = task
        logger.debug(f"Submitted task {task_id}")

        return task_id

    async def _run_async_task(
        self,
        task_id: str,
        func: Callable,
        *args,
        **kwargs,
    ):
        """Execute an async task."""
        await self._update_status(task_id, TaskStatus.RUNNING)

        try:
            result = await func(*args, **kwargs)
            await self._complete_task(task_id, result)
        except asyncio.CancelledError:
            await self._update_status(task_id, TaskStatus.CANCELLED)
            raise
        except Exception as e:
            await self._fail_task(task_id, str(e))
            logger.error(f"Task {task_id} failed: {e}")

    async def _run_sync_task(
        self,
        task_id: str,
        func: Callable,
        *args,
        **kwargs,
    ):
        """Execute a sync task in thread pool."""
        await self._update_status(task_id, TaskStatus.RUNNING)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                self._executor,
                lambda: func(*args, **kwargs),
            )
            await self._complete_task(task_id, result)
        except asyncio.CancelledError:
            await self._update_status(task_id, TaskStatus.CANCELLED)
            raise
        except Exception as e:
            await self._fail_task(task_id, str(e))
            logger.error(f"Task {task_id} failed: {e}")

    async def _update_status(self, task_id: str, status: TaskStatus):
        """Update task status."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = status
                if status == TaskStatus.RUNNING:
                    self._tasks[task_id].started_at = datetime.utcnow()

    async def _complete_task(self, task_id: str, result: Any):
        """Mark task as completed."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = TaskStatus.COMPLETED
                self._tasks[task_id].result = result
                self._tasks[task_id].completed_at = datetime.utcnow()
            if task_id in self._pending_futures:
                del self._pending_futures[task_id]

    async def _fail_task(self, task_id: str, error: str):
        """Mark task as failed."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = TaskStatus.FAILED
                self._tasks[task_id].error = error
                self._tasks[task_id].completed_at = datetime.utcnow()
            if task_id in self._pending_futures:
                del self._pending_futures[task_id]

    async def _cleanup_old_tasks(self):
        """Remove old completed tasks when at capacity."""
        if len(self._tasks) >= self.max_tasks:
            # Remove oldest completed tasks
            completed = [
                (tid, t) for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            completed.sort(key=lambda x: x[1].completed_at or datetime.min)

            to_remove = len(self._tasks) - self.max_tasks + 100
            for tid, _ in completed[:to_remove]:
                del self._tasks[tid]

    async def get_status(self, task_id: str) -> Optional[TaskResult]:
        """Get task status and result."""
        return self._tasks.get(task_id)

    async def get_result(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> TaskResult:
        """
        Wait for task completion and get result.

        Args:
            task_id: Task ID to wait for
            timeout: Maximum seconds to wait (None = wait forever)

        Returns:
            TaskResult with status and result

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            KeyError: If task_id not found
        """
        if task_id not in self._tasks:
            raise KeyError(f"Task not found: {task_id}")

        # If task is still running, wait for it
        if task_id in self._pending_futures:
            try:
                await asyncio.wait_for(
                    self._pending_futures[task_id],
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                raise
            except Exception:
                pass  # Task failed, result will show error

        return self._tasks[task_id]

    async def cancel(self, task_id: str) -> bool:
        """
        Cancel a pending or running task.

        Returns:
            True if task was cancelled, False if not found or already done
        """
        if task_id in self._pending_futures:
            self._pending_futures[task_id].cancel()
            return True
        return False

    def get_all_tasks(self) -> Dict[str, TaskResult]:
        """Get all task statuses."""
        return dict(self._tasks)

    def get_stats(self) -> Dict[str, Any]:
        """Get task manager statistics."""
        statuses = {}
        for task in self._tasks.values():
            statuses[task.status] = statuses.get(task.status, 0) + 1

        return {
            "total_tasks": len(self._tasks),
            "pending_tasks": len(self._pending_futures),
            "max_workers": self.max_workers,
            "max_tasks": self.max_tasks,
            "by_status": statuses,
        }

    async def shutdown(self, wait: bool = True):
        """
        Shutdown the task manager.

        Args:
            wait: Wait for pending tasks to complete
        """
        if wait:
            # Wait for all pending tasks
            if self._pending_futures:
                await asyncio.gather(
                    *self._pending_futures.values(),
                    return_exceptions=True,
                )
        else:
            # Cancel all pending tasks
            for task in self._pending_futures.values():
                task.cancel()

        self._executor.shutdown(wait=wait)
        logger.info("Task manager shutdown complete")


# Global task manager instance
_task_manager: Optional[BackgroundTaskManager] = None


def get_task_manager() -> BackgroundTaskManager:
    """Get the global task manager singleton."""
    global _task_manager
    if _task_manager is None:
        settings = get_settings()
        _task_manager = BackgroundTaskManager(
            max_workers=getattr(settings.api, 'async_max_workers', 10),
            max_tasks=getattr(settings.api, 'async_max_tasks', 1000),
        )
    return _task_manager


async def run_async(
    func: Callable,
    *args,
    timeout: Optional[float] = None,
    **kwargs,
) -> Any:
    """
    Run a function asynchronously and wait for result.

    Convenience wrapper that submits to task manager and waits.

    Args:
        func: Function to execute
        *args: Positional arguments
        timeout: Maximum wait time in seconds
        **kwargs: Keyword arguments

    Returns:
        Function result

    Raises:
        asyncio.TimeoutError: If timeout exceeded
        Exception: If function raised an exception
    """
    manager = get_task_manager()
    task_id = await manager.submit(func, *args, **kwargs)
    result = await manager.get_result(task_id, timeout=timeout)

    if result.status == TaskStatus.FAILED:
        raise RuntimeError(f"Task failed: {result.error}")

    return result.result


async def run_in_background(
    func: Callable,
    *args,
    callback: Optional[Callable[[TaskResult], None]] = None,
    **kwargs,
) -> str:
    """
    Run a function in background without waiting.

    Args:
        func: Function to execute
        *args: Positional arguments
        callback: Optional callback when task completes
        **kwargs: Keyword arguments

    Returns:
        Task ID for status tracking
    """
    manager = get_task_manager()
    task_id = await manager.submit(func, *args, **kwargs)

    if callback:
        # Schedule callback
        async def wait_and_callback():
            result = await manager.get_result(task_id)
            callback(result)

        asyncio.create_task(wait_and_callback())

    return task_id


async def parallel_execute(
    tasks: List[tuple],
    max_concurrent: int = 10,
) -> List[TaskResult]:
    """
    Execute multiple tasks in parallel with concurrency limit.

    Args:
        tasks: List of (func, args, kwargs) tuples
        max_concurrent: Maximum concurrent executions

    Returns:
        List of TaskResult objects in same order as input
    """
    manager = get_task_manager()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_with_semaphore(func, args, kwargs):
        async with semaphore:
            task_id = await manager.submit(func, *args, **kwargs)
            return await manager.get_result(task_id)

    coroutines = []
    for item in tasks:
        if len(item) == 1:
            func, args, kwargs = item[0], (), {}
        elif len(item) == 2:
            func, args, kwargs = item[0], item[1], {}
        else:
            func, args, kwargs = item[0], item[1], item[2]

        coroutines.append(run_with_semaphore(func, args, kwargs))

    return await asyncio.gather(*coroutines)

