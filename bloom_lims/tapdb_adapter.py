"""
BLOOM ↔ TapDB Adapter Module.

This adapter delegates connection resolution and runtime behavior to
daylily-tapdb while exposing BLOOM-compatible ORM class wiring.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from daylily_tapdb import TAPDBConnection
from daylily_tapdb.models.audit import audit_log
from daylily_tapdb.models.base import Base as TapDBBase, tapdb_core
from daylily_tapdb.models.instance import (
    action_instance,
    actor_instance,
    container_instance,
    content_instance,
    data_instance,
    equipment_instance,
    file_instance,
    generic_instance,
    health_event_instance,
    subject_instance,
    test_requisition_instance,
    workflow_instance,
    workflow_step_instance,
)
from daylily_tapdb.models.lineage import (
    action_instance_lineage,
    actor_instance_lineage,
    container_instance_lineage,
    content_instance_lineage,
    data_instance_lineage,
    equipment_instance_lineage,
    file_instance_lineage,
    generic_instance_lineage,
    health_event_instance_lineage,
    subject_instance_lineage,
    test_requisition_instance_lineage,
    workflow_instance_lineage,
    workflow_step_instance_lineage,
)
from daylily_tapdb.models.template import (
    action_template,
    actor_template,
    container_template,
    content_template,
    data_template,
    equipment_template,
    file_template,
    generic_template,
    health_event_template,
    subject_template,
    test_requisition_template,
    workflow_step_template,
    workflow_template,
)

from bloom_lims.config import get_tapdb_db_config
from bloom_lims.tapdb_metrics import db_username_var, maybe_install_engine_metrics


def _translate_bloom_kwargs(kwargs: dict) -> dict:
    """Preserve kwargs as-is using canonical TapDB field names."""
    return dict(kwargs)


def _patch_init_for_bloom_compat(cls) -> None:
    """Patch class __init__ once to preserve constructor passthrough."""
    if getattr(cls, "__bloom_init_patched__", False):
        return

    original_init = cls.__init__

    def patched_init(self, **kwargs):
        original_init(self, **_translate_bloom_kwargs(kwargs))

    cls.__init__ = patched_init
    cls.__bloom_init_patched__ = True


file_set_template = file_template
file_reference_template = file_template
file_set_instance = file_instance
file_reference_instance = file_instance
file_set_instance_lineage = file_instance_lineage
file_reference_instance_lineage = file_instance_lineage

bloom_core = tapdb_core
Base = TapDBBase


class _TransactionContext:
    """Compatibility transaction context manager."""

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__ + "._TransactionContext")

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.logger.warning(
                "Transaction rollback due to: %s: %s", exc_type.__name__, exc_val
            )
            self.session.rollback()
        else:
            try:
                self.session.commit()
            except Exception as exc:
                self.logger.error("Commit failed, rolling back: %s", exc)
                self.session.rollback()
                raise
        return False


class _BLOOMBaseProxy:
    """Automap-like proxy exposing `.classes` for legacy BLOOM code."""

    def __init__(self) -> None:
        self.metadata = TapDBBase.metadata
        self.classes = SimpleNamespace()


class BLOOMdb3:
    """BLOOM database adapter powered exclusively by daylily-tapdb."""

    def __init__(
        self,
        db_url_prefix: str = "postgresql://",
        db_hostname: Optional[str] = None,
        db_pass: Optional[str] = None,
        db_user: Optional[str] = None,
        db_name: Optional[str] = None,
        app_username: str = "bloomdborm",
        echo_sql: Optional[bool] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
    ):
        self.logger = logging.getLogger(__name__ + ".BLOOMdb3")
        self.app_username = app_username

        # Best-effort attribution for TapDB-style DB metrics.
        # (The request middleware sets path/method; the DB adapter tags username.)
        try:
            db_username_var.set(app_username)
        except Exception:
            pass

        # Legacy arguments remain accepted; TapDB config is authoritative.
        if any([db_url_prefix != "postgresql://", db_hostname, db_pass, db_user, db_name]):
            self.logger.warning(
                "Legacy BLOOMdb3 connection arguments are deprecated and ignored; "
                "TapDB runtime config is authoritative."
            )

        cfg = get_tapdb_db_config()
        engine_type = cfg.get("engine_type", "local")
        host = cfg["host"]
        port = cfg["port"]
        region = cfg.get("region", "us-west-2")
        iam_auth = str(cfg.get("iam_auth", "true")).lower() in ("true", "1", "yes")

        self._conn = TAPDBConnection(
            db_hostname=f"{host}:{port}",
            db_user=cfg["user"],
            db_pass=cfg.get("password") or "",
            db_name=cfg["database"],
            app_username=app_username,
            echo_sql=echo_sql,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            engine_type="aurora" if engine_type == "aurora" else None,
            region=region,
            iam_auth=iam_auth,
        )

        self.engine = self._conn.engine
        # Install TapDB-style per-query metrics once per engine.
        try:
            maybe_install_engine_metrics(
                self.engine, env_name=os.environ.get("TAPDB_ENV", "dev")
            )
        except Exception:
            # Metrics are best-effort; never block DB init.
            pass
        self._Session = self._conn._Session
        self.session = self._Session()

        self.Base = _BLOOMBaseProxy()
        self._register_orm_classes()
        self._set_session_username(self.session)

    def _set_session_username(self, session: Session) -> None:
        """Set audit username for the current session."""
        try:
            session.execute(
                text("SET session.current_username = :username"),
                {"username": self.app_username},
            )
        except Exception as exc:
            self.logger.warning("Could not set session username: %s", exc)

    def _register_orm_classes(self) -> None:
        classes_to_register = [
            generic_template,
            generic_instance,
            generic_instance_lineage,
            workflow_template,
            workflow_step_template,
            container_template,
            content_template,
            equipment_template,
            data_template,
            test_requisition_template,
            actor_template,
            action_template,
            health_event_template,
            file_template,
            subject_template,
            workflow_instance,
            workflow_step_instance,
            container_instance,
            content_instance,
            equipment_instance,
            data_instance,
            test_requisition_instance,
            actor_instance,
            action_instance,
            health_event_instance,
            file_instance,
            subject_instance,
            workflow_instance_lineage,
            workflow_step_instance_lineage,
            container_instance_lineage,
            content_instance_lineage,
            equipment_instance_lineage,
            data_instance_lineage,
            test_requisition_instance_lineage,
            actor_instance_lineage,
            action_instance_lineage,
            health_event_instance_lineage,
            file_instance_lineage,
            subject_instance_lineage,
            audit_log,
        ]

        for cls in classes_to_register:
            _patch_init_for_bloom_compat(cls)
            setattr(self.Base.classes, cls.__name__, cls)

        setattr(self.Base.classes, "file_set_template", file_template)
        setattr(self.Base.classes, "file_reference_template", file_template)
        setattr(self.Base.classes, "file_set_instance", file_instance)
        setattr(self.Base.classes, "file_reference_instance", file_instance)
        setattr(self.Base.classes, "file_set_instance_lineage", file_instance_lineage)
        setattr(self.Base.classes, "file_reference_instance_lineage", file_instance_lineage)

    def __enter__(self) -> "BLOOMdb3":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.session.rollback()
        self.close()
        return False

    def transaction(self):
        return _TransactionContext(self.session)

    def new_session(self) -> Session:
        session = self._Session()
        self._set_session_username(session)
        return session

    def close(self) -> None:
        if self.session:
            try:
                self.session.close()
            except Exception as exc:
                self.logger.warning("Error closing session: %s", exc)
        self._conn.close()


__all__ = [
    "Base",
    "bloom_core",
    "tapdb_core",
    "BLOOMdb3",
    "generic_template",
    "generic_instance",
    "generic_instance_lineage",
    "workflow_template",
    "workflow_step_template",
    "container_template",
    "content_template",
    "equipment_template",
    "data_template",
    "test_requisition_template",
    "actor_template",
    "action_template",
    "health_event_template",
    "file_template",
    "subject_template",
    "workflow_instance",
    "workflow_step_instance",
    "container_instance",
    "content_instance",
    "equipment_instance",
    "data_instance",
    "test_requisition_instance",
    "actor_instance",
    "action_instance",
    "health_event_instance",
    "file_instance",
    "subject_instance",
    "workflow_instance_lineage",
    "workflow_step_instance_lineage",
    "container_instance_lineage",
    "content_instance_lineage",
    "equipment_instance_lineage",
    "data_instance_lineage",
    "test_requisition_instance_lineage",
    "actor_instance_lineage",
    "action_instance_lineage",
    "health_event_instance_lineage",
    "file_instance_lineage",
    "subject_instance_lineage",
    "file_set_template",
    "file_reference_template",
    "file_set_instance",
    "file_reference_instance",
    "file_set_instance_lineage",
    "file_reference_instance_lineage",
    "audit_log",
]
