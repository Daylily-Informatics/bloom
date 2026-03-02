"""
BLOOM LIMS Read Replica Compatibility Layer.

Bloom no longer owns engine/session construction. This module preserves the
public read-replica API surface while delegating connectivity to TapDB via
`BLOOMdb3`.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy.orm import Session

from bloom_lims.config import get_tapdb_db_config
from bloom_lims.db import BLOOMdb3

logger = logging.getLogger(__name__)


@dataclass
class ReplicaConfig:
    """Configuration for a read replica."""

    host: str
    port: int = 5432
    weight: int = 1
    max_lag_seconds: int = 30
    enabled: bool = True


@dataclass
class ReplicaStatus:
    """Health/status snapshot for a configured replica."""

    host: str
    port: int
    healthy: bool = False
    last_check: float = 0.0
    replication_lag_seconds: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None


def _build_primary_url() -> str:
    cfg = get_tapdb_db_config()
    auth = cfg["user"]
    if cfg.get("password"):
        auth = f"{cfg['user']}:{cfg['password']}"
    return f"postgresql://{auth}@{cfg['host']}:{cfg['port']}/{cfg['database']}"


class ReplicaRouter:
    """
    Compatibility router for read/write session APIs.

    Bloom no longer creates SQLAlchemy engines directly. When replica configs
    are provided, the router records them for observability but all sessions
    resolve through TapDB-managed runtime configuration.
    """

    def __init__(
        self,
        primary_url: Optional[str] = None,
        replicas: Optional[List[ReplicaConfig]] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
        health_check_interval: int = 30,
        echo_sql: bool = False,
    ):
        self.primary_url = primary_url or _build_primary_url()
        self.replicas = replicas or []
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.health_check_interval = health_check_interval
        self.echo_sql = echo_sql

        self._lock = threading.Lock()
        self._replica_status: List[ReplicaStatus] = []
        self._initialize_replica_status()

        if self.replicas:
            logger.warning(
                "Replica routing is compatibility-only in tapdb mode; "
                "sessions resolve using TapDB-managed primary config."
            )

    def _initialize_replica_status(self) -> None:
        now = time.time()
        self._replica_status = [
            ReplicaStatus(
                host=replica.host,
                port=replica.port,
                healthy=False,
                last_check=now,
                error_count=1,
                last_error=(
                    "Bloom-side replica engines are disabled; "
                    "TapDB controls DB routing."
                ),
            )
            for replica in self.replicas
            if replica.enabled
        ]

    def _open_session(self) -> tuple[BLOOMdb3, Session]:
        bdb = BLOOMdb3(app_username="bloom-replica-router")
        return bdb, bdb.new_session()

    @contextmanager
    def read_session(self) -> Generator[Session, None, None]:
        bdb, session = self._open_session()
        try:
            yield session
        finally:
            try:
                session.close()
            finally:
                bdb.close()

    @contextmanager
    def write_session(self) -> Generator[Session, None, None]:
        bdb, session = self._open_session()
        try:
            yield session
        finally:
            try:
                session.close()
            finally:
                bdb.close()

    @contextmanager
    def transaction(self) -> Generator[Session, None, None]:
        bdb, session = self._open_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            try:
                session.close()
            finally:
                bdb.close()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            statuses = [status.__dict__.copy() for status in self._replica_status]
        return {
            "mode": "tapdb-managed",
            "primary": {
                "url": self.primary_url.split("@")[-1] if "@" in self.primary_url else self.primary_url,
                "healthy": True,
            },
            "replicas": statuses,
            "total_replicas": len(statuses),
            "healthy_replicas": sum(1 for s in statuses if s.get("healthy")),
        }

    def close(self) -> None:
        return


_router: Optional[ReplicaRouter] = None
_router_lock = threading.Lock()


def get_replica_router(force_new: bool = False) -> ReplicaRouter:
    """Get singleton replica router."""

    global _router
    with _router_lock:
        if _router is None or force_new:
            if _router is not None:
                _router.close()
            _router = ReplicaRouter()
    return _router


def configure_replicas(replicas: List[Dict[str, Any]]) -> ReplicaRouter:
    """Configure compatibility replica metadata programmatically."""

    global _router
    replica_configs = [
        ReplicaConfig(
            host=replica.get("host", "localhost"),
            port=replica.get("port", 5432),
            weight=replica.get("weight", 1),
            max_lag_seconds=replica.get("max_lag_seconds", 30),
            enabled=replica.get("enabled", True),
        )
        for replica in replicas
    ]

    with _router_lock:
        if _router is not None:
            _router.close()
        _router = ReplicaRouter(replicas=replica_configs)

    return _router
