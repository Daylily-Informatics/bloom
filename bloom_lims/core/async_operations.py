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
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.orm import Session

from bloom_lims.config import get_settings
from bloom_lims.db import BLOOMdb3

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

    This is a compatibility wrapper around TapDB-managed sync sessions. It
    preserves async call-sites without Bloom owning async engine creation.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        echo: bool = False,
        app_username: str = "bloom-async",
    ):
        self.app_username = app_username
        self._bdb: Optional[BLOOMdb3] = None
        self._session: Optional[Session] = None

        # Legacy args are accepted for compatibility but ignored in tapdb mode.
        if connection_string:
            logger.warning(
                "AsyncDatabaseSession.connection_string is ignored; "
                "TapDB runtime config is authoritative."
            )
        if pool_size != 5 or max_overflow != 10 or echo:
            logger.warning(
                "AsyncDatabaseSession pool/echo options are ignored in tapdb mode."
            )

    async def __aenter__(self) -> "AsyncSessionProxy":
        self._bdb = BLOOMdb3(app_username=self.app_username)
        self._session = self._bdb.new_session()
        return AsyncSessionProxy(self._session)

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if not self._session:
            return False
        try:
            if exc_type:
                await asyncio.to_thread(self._session.rollback)
            else:
                await asyncio.to_thread(self._session.commit)
        finally:
            await asyncio.to_thread(self._session.close)
            if self._bdb:
                self._bdb.close()
            self._session = None
            self._bdb = None
        return False

    @asynccontextmanager
    async def session(self):
        """Get an async session context."""
        async with self as session:
            yield session

    async def execute(self, query: str, params: Optional[Dict] = None) -> Any:
        """Execute a raw SQL query."""
        async with self.session() as session:
            return await session.execute(query, params or {})

    @staticmethod
    async def close():
        """Compatibility no-op (sessions are scoped per context)."""
        return


class AsyncSessionProxy:
    """Awaitable wrapper around a sync SQLAlchemy Session."""

    def __init__(self, session: Session):
        self._session = session

    @property
    def sync_session(self) -> Session:
        return self._session

    async def execute(self, statement: Any, params: Optional[Dict] = None) -> Any:
        def _execute():
            if isinstance(statement, str):
                return self._session.execute(text(statement), params or {})
            return self._session.execute(statement, params or {})

        return await asyncio.to_thread(_execute)

    async def add(self, obj: Any) -> None:
        await asyncio.to_thread(self._session.add, obj)

    async def add_all(self, objects: List[Any]) -> None:
        await asyncio.to_thread(self._session.add_all, objects)

    async def flush(self) -> None:
        await asyncio.to_thread(self._session.flush)

    async def commit(self) -> None:
        await asyncio.to_thread(self._session.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._session.rollback)

    async def close(self) -> None:
        await asyncio.to_thread(self._session.close)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._session, name)
        if callable(attr):
            async def _async_call(*args, **kwargs):
                return await asyncio.to_thread(attr, *args, **kwargs)

            return _async_call
        return attr


def _unwrap_sync_session(session: Any) -> Session:
    if isinstance(session, AsyncSessionProxy):
        return session.sync_session
    return session


async def async_query(
    session: Any,
    model: Any,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[Any]:
    """Run a non-blocking ORM query against a TapDB-managed sync session."""

    sync_session = _unwrap_sync_session(session)

    def _run():
        query = sync_session.query(model)
        for key, value in (filters or {}).items():
            query = query.filter(getattr(model, key) == value)
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()

    return await asyncio.to_thread(_run)


async def async_bulk_insert(
    session: Any,
    objects: List[Any],
    chunk_size: int = 1000,
) -> int:
    """Insert objects in chunks using TapDB-managed sync sessions."""

    sync_session = _unwrap_sync_session(session)

    def _run() -> int:
        inserted = 0
        for i in range(0, len(objects), chunk_size):
            chunk = objects[i : i + chunk_size]
            sync_session.add_all(chunk)
            sync_session.flush()
            inserted += len(chunk)
        return inserted

    return await asyncio.to_thread(_run)


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
        task_id = task_id or f"task_{secrets.token_hex(16)}"

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
