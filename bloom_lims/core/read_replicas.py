"""
BLOOM LIMS Read Replica Support

Provides database read replica routing for scaling read-heavy workloads.

Usage:
    from bloom_lims.core.read_replicas import ReplicaRouter, get_replica_router
    
    # Get configured router
    router = get_replica_router()
    
    # Get session for read operations (may use replica)
    with router.read_session() as session:
        results = session.query(Model).all()
    
    # Get session for write operations (always uses primary)
    with router.write_session() as session:
        session.add(new_object)
        session.commit()

Features:
    - Automatic routing of reads to replicas
    - Round-robin load balancing across replicas
    - Automatic failover to primary on replica failure
    - Configurable lag tolerance
    - Health checking
"""

import logging
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ReplicaConfig:
    """Configuration for a read replica."""
    host: str
    port: int = 5432
    weight: int = 1  # Load balancing weight
    max_lag_seconds: int = 30  # Maximum acceptable replication lag
    enabled: bool = True


@dataclass
class ReplicaStatus:
    """Health status of a replica."""
    host: str
    port: int
    healthy: bool = True
    last_check: float = 0.0
    replication_lag_seconds: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None


class ReplicaRouter:
    """
    Database router that directs reads to replicas and writes to primary.
    
    Implements:
        - Round-robin load balancing with weights
        - Automatic failover on replica failure
        - Health checking with configurable intervals
        - Replication lag awareness
    """
    
    def __init__(
        self,
        primary_url: str,
        replicas: List[ReplicaConfig] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
        health_check_interval: int = 30,
        echo_sql: bool = False,
    ):
        """
        Initialize replica router.
        
        Args:
            primary_url: SQLAlchemy connection URL for primary database
            replicas: List of replica configurations
            pool_size: Connection pool size per database
            max_overflow: Max connections above pool_size
            pool_timeout: Seconds to wait for connection
            pool_recycle: Seconds before connection recycled
            health_check_interval: Seconds between health checks
            echo_sql: Whether to log SQL statements
        """
        self.primary_url = primary_url
        self.replicas = replicas or []
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.health_check_interval = health_check_interval
        self.echo_sql = echo_sql
        
        # Create primary engine
        self._primary_engine = self._create_engine(primary_url)
        self._primary_session_factory = sessionmaker(bind=self._primary_engine)
        
        # Create replica engines
        self._replica_engines: List[Engine] = []
        self._replica_session_factories: List[sessionmaker] = []
        self._replica_status: List[ReplicaStatus] = []
        
        self._setup_replicas()
        
        # Round-robin index and lock
        self._rr_index = 0
        self._lock = threading.Lock()
        
        # Start health checker
        self._health_thread: Optional[threading.Thread] = None
        self._stop_health_check = threading.Event()
        
        if self.replicas:
            self._start_health_checker()
    
    def _create_engine(self, url: str) -> Engine:
        """Create SQLAlchemy engine with pooling."""
        return create_engine(
            url,
            echo=self.echo_sql,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=True,
        )
    
    def _setup_replicas(self) -> None:
        """Initialize replica connections."""
        settings = get_settings()
        
        for replica in self.replicas:
            if not replica.enabled:
                continue

            try:
                # Build replica URL from primary URL pattern
                replica_url = self._build_replica_url(replica)
                engine = self._create_engine(replica_url)

                self._replica_engines.append(engine)
                self._replica_session_factories.append(sessionmaker(bind=engine))
                self._replica_status.append(ReplicaStatus(
                    host=replica.host,
                    port=replica.port,
                    healthy=True,
                    last_check=time.time(),
                ))

                logger.info(f"Added read replica: {replica.host}:{replica.port}")

            except Exception as e:
                logger.error(f"Failed to add replica {replica.host}:{replica.port}: {e}")

    def _build_replica_url(self, replica: ReplicaConfig) -> str:
        """Build connection URL for replica from primary URL."""
        # Parse primary URL and replace host/port
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(self.primary_url)

        # Reconstruct with replica host/port
        netloc = f"{parsed.username}:{parsed.password}@{replica.host}:{replica.port}" \
            if parsed.password else f"{parsed.username}@{replica.host}:{replica.port}"

        return urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))

    def _start_health_checker(self) -> None:
        """Start background health check thread."""
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name="replica-health-checker",
        )
        self._health_thread.start()
        logger.info("Started replica health checker")

    def _health_check_loop(self) -> None:
        """Background loop to check replica health."""
        while not self._stop_health_check.is_set():
            self._check_all_replicas()
            self._stop_health_check.wait(self.health_check_interval)

    def _check_all_replicas(self) -> None:
        """Check health of all replicas."""
        for i, (engine, status) in enumerate(zip(self._replica_engines, self._replica_status)):
            try:
                with engine.connect() as conn:
                    # Check replication lag using pg_stat_replication or pg_last_wal_replay_lsn
                    result = conn.execute(text("""
                        SELECT CASE
                            WHEN pg_is_in_recovery() THEN
                                EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
                            ELSE 0
                        END as lag_seconds
                    """))
                    row = result.fetchone()
                    lag = row[0] if row and row[0] else 0.0

                    status.replication_lag_seconds = lag
                    status.last_check = time.time()

                    # Mark unhealthy if lag exceeds threshold
                    replica_config = self.replicas[i]
                    was_healthy = status.healthy
                    status.healthy = lag <= replica_config.max_lag_seconds

                    if was_healthy and not status.healthy:
                        logger.warning(
                            f"Replica {status.host}:{status.port} marked unhealthy "
                            f"(lag: {lag:.1f}s > {replica_config.max_lag_seconds}s)"
                        )
                    elif not was_healthy and status.healthy:
                        logger.info(f"Replica {status.host}:{status.port} recovered")

                    status.error_count = 0
                    status.last_error = None

            except Exception as e:
                status.error_count += 1
                status.last_error = str(e)
                status.healthy = False
                logger.warning(f"Replica health check failed for {status.host}:{status.port}: {e}")

    def _get_replica_index(self) -> Optional[int]:
        """Get next healthy replica index using weighted round-robin."""
        with self._lock:
            healthy_indices = [
                (i, self.replicas[i].weight)
                for i, status in enumerate(self._replica_status)
                if status.healthy
            ]

            if not healthy_indices:
                return None

            # Weighted selection
            total_weight = sum(w for _, w in healthy_indices)
            if total_weight == 0:
                return healthy_indices[0][0]

            # Simple round-robin for now
            self._rr_index = (self._rr_index + 1) % len(healthy_indices)
            return healthy_indices[self._rr_index][0]

    @contextmanager
    def read_session(self) -> Generator[Session, None, None]:
        """
        Get a session for read operations.

        May use a read replica if available and healthy.
        Falls back to primary if no healthy replicas.
        """
        replica_idx = self._get_replica_index()

        if replica_idx is not None:
            session = self._replica_session_factories[replica_idx]()
            logger.debug(f"Using replica {self._replica_status[replica_idx].host} for read")
        else:
            session = self._primary_session_factory()
            logger.debug("Using primary for read (no healthy replicas)")

        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def write_session(self) -> Generator[Session, None, None]:
        """
        Get a session for write operations.

        Always uses the primary database.
        """
        session = self._primary_session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def transaction(self) -> Generator[Session, None, None]:
        """
        Get a session within a transaction context.

        Commits on success, rolls back on exception.
        """
        session = self._primary_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_status(self) -> Dict[str, Any]:
        """Get current status of primary and all replicas."""
        return {
            "primary": {
                "url": self.primary_url.split("@")[-1] if "@" in self.primary_url else self.primary_url,
                "healthy": True,
            },
            "replicas": [
                {
                    "host": status.host,
                    "port": status.port,
                    "healthy": status.healthy,
                    "replication_lag_seconds": status.replication_lag_seconds,
                    "last_check": status.last_check,
                    "error_count": status.error_count,
                    "last_error": status.last_error,
                }
                for status in self._replica_status
            ],
            "total_replicas": len(self._replica_status),
            "healthy_replicas": sum(1 for s in self._replica_status if s.healthy),
        }

    def close(self) -> None:
        """Close all connections and stop health checker."""
        self._stop_health_check.set()
        if self._health_thread:
            self._health_thread.join(timeout=5)

        self._primary_engine.dispose()
        for engine in self._replica_engines:
            engine.dispose()

        logger.info("Closed all database connections")


# Global router instance
_router: Optional[ReplicaRouter] = None
_router_lock = threading.Lock()


def get_replica_router(force_new: bool = False) -> ReplicaRouter:
    """
    Get the configured replica router singleton.

    Creates router from settings if not already initialized.

    Args:
        force_new: Force creation of new router instance

    Returns:
        ReplicaRouter instance
    """
    global _router

    with _router_lock:
        if _router is None or force_new:
            if _router is not None:
                _router.close()

            settings = get_settings()

            # Build primary URL
            primary_url = settings.database.connection_string

            # Build replica configs from settings
            replicas = []
            replica_settings = getattr(settings.database, 'read_replicas', [])

            for r in replica_settings:
                if isinstance(r, dict):
                    replicas.append(ReplicaConfig(
                        host=r.get('host', 'localhost'),
                        port=r.get('port', 5432),
                        weight=r.get('weight', 1),
                        max_lag_seconds=r.get('max_lag_seconds', 30),
                        enabled=r.get('enabled', True),
                    ))
                elif isinstance(r, ReplicaConfig):
                    replicas.append(r)

            _router = ReplicaRouter(
                primary_url=primary_url,
                replicas=replicas,
                pool_size=settings.database.pool_size,
                max_overflow=settings.database.max_overflow,
                pool_timeout=settings.database.pool_timeout,
                pool_recycle=settings.database.pool_recycle,
                echo_sql=settings.database.echo,
            )

            logger.info(f"Initialized replica router with {len(replicas)} replicas")

        return _router


def configure_replicas(replicas: List[Dict[str, Any]]) -> ReplicaRouter:
    """
    Configure read replicas programmatically.

    Args:
        replicas: List of replica configurations
            [{"host": "replica1.example.com", "port": 5432, "weight": 1}, ...]

    Returns:
        Configured ReplicaRouter

    Usage:
        router = configure_replicas([
            {"host": "replica1.db.example.com", "port": 5432, "weight": 2},
            {"host": "replica2.db.example.com", "port": 5432, "weight": 1},
        ])
    """
    global _router

    settings = get_settings()
    primary_url = settings.database.connection_string

    replica_configs = [
        ReplicaConfig(
            host=r.get('host', 'localhost'),
            port=r.get('port', 5432),
            weight=r.get('weight', 1),
            max_lag_seconds=r.get('max_lag_seconds', 30),
            enabled=r.get('enabled', True),
        )
        for r in replicas
    ]

    with _router_lock:
        if _router is not None:
            _router.close()

        _router = ReplicaRouter(
            primary_url=primary_url,
            replicas=replica_configs,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout,
            pool_recycle=settings.database.pool_recycle,
            echo_sql=settings.database.echo,
        )

    return _router

