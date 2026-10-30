"""
BLOOM ↔ TapDB Adapter Module.

This adapter delegates connection resolution and runtime behavior to
daylily-tapdb while exposing BLOOM ORM class wiring.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

from daylily_tapdb import TAPDBConnection
from daylily_tapdb.models.audit import audit_log
from daylily_tapdb.models.base import Base as TapDBBase
from daylily_tapdb.models.base import tapdb_core
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
    workflow_step_template,
    workflow_template,
)
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session, sessionmaker

from bloom_lims.config import (
    apply_runtime_environment,
    get_settings,
    get_tapdb_db_config,
)
from bloom_lims.request_db import register_request_database
from bloom_lims.tapdb_metrics import db_username_var, maybe_install_engine_metrics

_KNOWN_LINEAGE_IDENTITIES = (
    "generic_instance_lineage",
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
)


def _explicit_bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise RuntimeError(f"Bloom TapDB {field} must be an explicit boolean")


class _LineageQueryProxy:
    """Lightweight proxy that preserves iterable/.all() behavior for lineage access."""

    def __init__(self, query):
        self._query = query

    def __iter__(self):
        return iter(self._query)

    def __len__(self):
        if isinstance(self._query, list):
            return len(self._query)
        return self._query.count()

    def __bool__(self):
        if isinstance(self._query, list):
            return bool(self._query)
        return self._query.first() is not None

    def all(self):
        if isinstance(self._query, list):
            return list(self._query)
        return self._query.all()

    def first(self):
        if isinstance(self._query, list):
            return self._query[0] if self._query else None
        return self._query.first()

    def count(self):
        if isinstance(self._query, list):
            return len(self._query)
        return self._query.count()

    def __getitem__(self, item):
        return self._query[item]

    def __getattr__(self, name):
        return getattr(self._query, name)


def _query_lineages_for_instance(instance, *, fk_attr_name: str):
    """Return a query-like proxy for lineage traversal using canonical TapDB FKs."""
    session = object_session(instance)
    if session is None:
        return _LineageQueryProxy([])

    lineage_attr = getattr(generic_instance_lineage, fk_attr_name)
    query = (
        session.query(generic_instance_lineage)
        .filter(lineage_attr == instance.uid)
        .filter(
            generic_instance_lineage.polymorphic_discriminator.in_(
                _KNOWN_LINEAGE_IDENTITIES
            )
        )
    )
    return _LineageQueryProxy(query)


def get_parent_lineages(instance):
    """Return parent->child lineages using canonical TapDB FKs."""
    return _query_lineages_for_instance(instance, fk_attr_name="parent_instance_uid")


def get_child_lineages(instance):
    """Return child->parent lineages using canonical TapDB FKs."""
    return _query_lineages_for_instance(instance, fk_attr_name="child_instance_uid")


def _query_instance_for_lineage(lineage, *, fk_attr_name: str):
    """Resolve parent/child instance via explicit query against canonical TapDB FKs."""
    session = object_session(lineage)
    if session is None:
        return None

    instance_uid = getattr(lineage, fk_attr_name, None)
    if instance_uid is None:
        return None

    return (
        session.query(generic_instance)
        .filter(generic_instance.uid == instance_uid)
        .first()
    )


file_set_template = file_template
file_reference_template = file_template
file_set_instance = file_instance
file_reference_instance = file_instance
file_set_instance_lineage = file_instance_lineage
file_reference_instance_lineage = file_instance_lineage

bloom_core = tapdb_core
_MODEL_CLASSES = SimpleNamespace(
    generic_template=generic_template,
    generic_instance=generic_instance,
    generic_instance_lineage=generic_instance_lineage,
    workflow_template=workflow_template,
    workflow_step_template=workflow_step_template,
    container_template=container_template,
    content_template=content_template,
    equipment_template=equipment_template,
    data_template=data_template,
    actor_template=actor_template,
    action_template=action_template,
    health_event_template=health_event_template,
    file_template=file_template,
    file_set_template=file_set_template,
    file_reference_template=file_reference_template,
    subject_template=subject_template,
    workflow_instance=workflow_instance,
    workflow_step_instance=workflow_step_instance,
    container_instance=container_instance,
    content_instance=content_instance,
    equipment_instance=equipment_instance,
    data_instance=data_instance,
    actor_instance=actor_instance,
    action_instance=action_instance,
    health_event_instance=health_event_instance,
    file_instance=file_instance,
    file_set_instance=file_set_instance,
    file_reference_instance=file_reference_instance,
    subject_instance=subject_instance,
    workflow_instance_lineage=workflow_instance_lineage,
    workflow_step_instance_lineage=workflow_step_instance_lineage,
    container_instance_lineage=container_instance_lineage,
    content_instance_lineage=content_instance_lineage,
    equipment_instance_lineage=equipment_instance_lineage,
    data_instance_lineage=data_instance_lineage,
    actor_instance_lineage=actor_instance_lineage,
    action_instance_lineage=action_instance_lineage,
    health_event_instance_lineage=health_event_instance_lineage,
    file_instance_lineage=file_instance_lineage,
    file_set_instance_lineage=file_set_instance_lineage,
    file_reference_instance_lineage=file_reference_instance_lineage,
    subject_instance_lineage=subject_instance_lineage,
    audit_log=audit_log,
)
Base = SimpleNamespace(classes=_MODEL_CLASSES, metadata=TapDBBase.metadata)


class BLOOMdb3:
    def __init__(
        self,
        app_username: str = "bloomdborm",
        echo_sql: Optional[bool] = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
    ):
        self.logger = logging.getLogger(__name__ + ".BLOOMdb3")
        self.app_username = app_username
        runtime_ctx = apply_runtime_environment(get_settings())
        self.domain_code = runtime_ctx.domain_code
        self.owner_repo_name = runtime_ctx.owner_repo_name

        # Best-effort attribution for TapDB-style DB metrics.
        # (The request middleware sets path/method; the DB adapter tags username.)
        try:
            db_username_var.set(app_username)
        except Exception:
            pass

        cfg = get_tapdb_db_config()
        engine_type = cfg["engine_type"]
        if engine_type not in {"local", "aurora"}:
            raise RuntimeError(
                "Bloom requires an explicit local or aurora TapDB target"
            )
        host = cfg["host"]
        port = cfg["port"]
        region = cfg["region"]
        iam_auth = _explicit_bool(cfg["iam_auth"], "iam_auth")
        allow_global_rows = _explicit_bool(
            cfg["allow_global_claims"], "allow_global_claims"
        )
        if engine_type == "aurora" and not str(cfg.get("secret_arn") or "").strip():
            raise RuntimeError("Bloom Aurora runtime requires an explicit secret ARN")
        if engine_type == "aurora" and (
            not str(region).strip() or not cfg.get("server_port")
        ):
            raise RuntimeError("Bloom Aurora runtime requires region and server_port")

        self._conn = TAPDBConnection(
            db_hostname=f"{host}:{port}",
            db_hostaddr=cfg.get("hostaddr") or None,
            db_user=cfg["user"],
            db_pass=cfg.get("password") or "",
            db_name=cfg["database"],
            schema_name=cfg["schema_name"],
            app_username=app_username,
            echo_sql=bool(echo_sql),
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            engine_type="aurora" if engine_type == "aurora" else "local",
            region=region,
            iam_auth=iam_auth,
            secret_arn=cfg.get("secret_arn") or None,
            domain_code=self.domain_code,
            owner_repo_name=self.owner_repo_name,
            tenant_id=cfg.get("tenant_id") or None,
            additional_tenant_ids=tuple(cfg["additional_tenant_ids"]),
            allow_global_rows=allow_global_rows,
            config_identity=str(cfg["config_path"]),
            connection_role="runtime",
            aws_profile=runtime_ctx.aws_profile,
            sslrootcert=cfg.get("sslrootcert") or None,
            server_port=(int(cfg["server_port"]) if engine_type == "aurora" else None),
        )

        self.engine = self._conn.engine
        self.Base = Base
        # Install TapDB-style per-query metrics once per engine.
        try:
            maybe_install_engine_metrics(self.engine, env_name="target")
        except Exception:
            # Metrics are best-effort; never block DB init.
            pass
        self._closed = False
        self._sessions: list[Session] = []
        self._session_factory = sessionmaker(bind=self.engine)
        self.session = self._new_contextual_session()
        register_request_database(self)

    def _new_contextual_session(self) -> Session:
        """Create a caller-owned session with TapDB scope on every transaction."""
        if self._closed:
            raise RuntimeError("Cannot create a session on a closed Bloom database handle")
        session = self._session_factory()
        self._sessions.append(session)

        from dataclasses import replace
        from daylily_tapdb.security_context import apply_transaction_context
        from bloom_lims.attribution import current_attribution

        def install(connection):
            attribution = current_attribution()
            apply_transaction_context(connection, replace(self._conn.transaction_context(),
                                                          attribution=attribution),
                                      assert_runtime_role=self._conn.connection_role == "runtime")
            if self._conn.connection_role == "operator":
                from daylily_tapdb.security_context import assert_operator_role
                assert_operator_role(connection)
            session.info["bloom_installed_attribution"] = attribution

        @event.listens_for(session, "after_begin")
        def _install_context(
            _session: Session, transaction: object, connection: object
        ) -> None:
            if getattr(transaction, "parent", None) is None:
                install(connection)

        def refresh_identity():
            connection = session.connection()
            if session.info.get("bloom_installed_attribution") != current_attribution():
                install(connection)

        @event.listens_for(session, "do_orm_execute")
        def _attribute_statement(_state):
            refresh_identity()

        @event.listens_for(session, "before_flush")
        def _attribute_flush(_session, _context, _instances):
            refresh_identity()

        @event.listens_for(session, "after_soft_rollback")
        def _reset_attribution_observation(_session, _previous_transaction):
            session.info.pop("bloom_installed_attribution", None)

        from bloom_lims.revisions import install_revision_guard
        install_revision_guard(session)
        return session

    def __enter__(self) -> "BLOOMdb3":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.session.rollback()
        self.close()
        return False

    def transaction(self):
        return self.session.begin()

    def new_session(self) -> Session:
        return self._new_contextual_session()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            # Session.close rolls back unfinished reads/writes; never auto-commit.
            # Include sessions returned by new_session, not just the primary one.
            for session in self._sessions:
                try:
                    session.close()
                except Exception:
                    self.logger.exception("Error closing Bloom database session")
        finally:
            self._sessions.clear()
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
    "get_parent_lineages",
    "get_child_lineages",
    "audit_log",
]
