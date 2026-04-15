from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from daylily_tapdb import require_seeded_templates
from daylily_tapdb.factory import InstanceFactory
from daylily_tapdb.models.instance import generic_instance
from daylily_tapdb.templates import TemplateManager
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.config import get_settings
from bloom_lims.observability import ProjectionMetadata

ANOMALY_TEMPLATE_CODE = "bloom/ops/anomaly-record/1.0/"
ANOMALY_PREFIX = "BAN"


@dataclass(frozen=True)
class AnomalyRecord:
    id: str
    service: str
    environment: str
    category: str
    severity: str
    fingerprint: str
    summary: str
    first_seen_at: str
    last_seen_at: str
    occurrence_count: int
    redacted_context: dict[str, Any]
    source_view_url: str


def redact_context(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"authorization", "cookie", "set-cookie", "token", "secret", "password"}:
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = redact_context(item)
        return redacted
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    if isinstance(value, str):
        text = value
        for prefix in ("/documents/", "/patients/", "/subjects/"):
            if prefix in text:
                head, _, tail = text.partition(prefix)
                parts = tail.split("/", 1)
                if parts and parts[0].isdigit():
                    suffix = f"/{parts[1]}" if len(parts) > 1 else ""
                    text = f"{head}{prefix}{{id}}{suffix}"
        if "select " in text.lower():
            return "[redacted-sql]"
        return text
    return value


class TapdbAnomalyRepository:
    def __init__(self, db: Session):
        self.db = db
        self.domain_code = str(get_settings().tapdb.domain_code).strip().upper()
        self.templates = TemplateManager()
        self.factory = InstanceFactory(self.templates)
        self._templates_ready = False

    def projection(self, *, observed_at: str | None = None) -> ProjectionMetadata:
        seen_at = observed_at or datetime.now(UTC).isoformat()
        return ProjectionMetadata(
            state="ready",
            stale=False,
            observed_at=seen_at,
            last_synced_at=seen_at,
            detail=None,
        )

    def record(
        self,
        *,
        category: str,
        severity: str,
        fingerprint: str,
        summary: str,
        redacted_context: dict[str, Any] | None = None,
    ) -> AnomalyRecord:
        self._ensure_templates()
        now = datetime.now(UTC).isoformat()
        environment = get_settings().environment or "unknown"
        context = redact_context(redacted_context or {})
        existing = self._find_existing(
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            environment=environment,
        )
        if existing is None:
            instance = self.factory.create_instance(
                session=self.db,
                template_code=ANOMALY_TEMPLATE_CODE,
                name=summary[:120],
                properties={
                    "service": "bloom",
                    "environment": environment,
                    "category": category,
                    "severity": severity,
                    "fingerprint": fingerprint,
                    "summary": summary,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "occurrence_count": 1,
                    "redacted_context": context,
                },
            )
        else:
            props = self._props(existing)
            props["summary"] = summary
            props["last_seen_at"] = now
            props["occurrence_count"] = int(props.get("occurrence_count") or 0) + 1
            props["redacted_context"] = context
            self._write_props(existing, props)
            instance = existing
        self.db.commit()
        return self._to_record(instance)

    def list(self, *, skip: int = 0, limit: int = 100) -> list[AnomalyRecord]:
        self._ensure_templates()
        rows = [self._to_record(instance) for instance in self._instances()]
        rows.sort(key=lambda row: row.last_seen_at, reverse=True)
        return rows[skip : skip + limit]

    def get(self, anomaly_id: str) -> AnomalyRecord | None:
        self._ensure_templates()
        for instance in self._instances():
            if instance.euid == anomaly_id:
                return self._to_record(instance)
        return None

    def record_db_probe_failure(self, *, detail: str, latency_ms: float) -> AnomalyRecord:
        return self.record(
            category="database",
            severity="error",
            fingerprint=f"db:{hash(detail)}",
            summary="Bloom database probe failed",
            redacted_context={
                "detail": detail,
                "latency_ms": round(float(latency_ms), 3),
            },
        )

    def _ensure_templates(self) -> None:
        if self._templates_ready:
            return
        require_seeded_templates(
            self.db,
            [(ANOMALY_TEMPLATE_CODE, ANOMALY_PREFIX)],
            app_name="Bloom",
            domain_code=self.domain_code,
            template_manager=self.templates,
        )
        self._templates_ready = True

    def _find_existing(
        self,
        *,
        category: str,
        severity: str,
        fingerprint: str,
        environment: str,
    ) -> generic_instance | None:
        for instance in self._instances():
            props = self._props(instance)
            if (
                str(props.get("category") or "") == category
                and str(props.get("severity") or "") == severity
                and str(props.get("fingerprint") or "") == fingerprint
                and str(props.get("environment") or "") == environment
            ):
                return instance
        return None

    def _instances(self) -> list[generic_instance]:
        category, type_name, subtype, version = ANOMALY_TEMPLATE_CODE.strip("/").split("/")
        stmt = (
            select(generic_instance)
            .where(
                generic_instance.domain_code == self.domain_code,
                generic_instance.category == category,
                generic_instance.type == type_name,
                generic_instance.subtype == subtype,
                generic_instance.version == version,
                generic_instance.is_deleted.is_(False),
            )
            .order_by(generic_instance.created_dt.desc())
        )
        return list(self.db.execute(stmt).scalars())

    def _props(self, instance: generic_instance) -> dict[str, Any]:
        payload = instance.json_addl or {}
        if not isinstance(payload, dict):
            payload = {}
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            properties = {}
            payload["properties"] = properties
            instance.json_addl = payload
        return properties

    def _write_props(self, instance: generic_instance, properties: dict[str, Any]) -> None:
        payload = instance.json_addl or {}
        if not isinstance(payload, dict):
            payload = {}
        payload["properties"] = properties
        instance.json_addl = payload
        if hasattr(instance, "_sa_instance_state"):
            flag_modified(instance, "json_addl")

    def _to_record(self, instance: generic_instance) -> AnomalyRecord:
        props = self._props(instance)
        return AnomalyRecord(
            id=str(instance.euid),
            service=str(props.get("service") or "bloom"),
            environment=str(props.get("environment") or (get_settings().environment or "unknown")),
            category=str(props.get("category") or "unknown"),
            severity=str(props.get("severity") or "unknown"),
            fingerprint=str(props.get("fingerprint") or ""),
            summary=str(props.get("summary") or ""),
            first_seen_at=str(props.get("first_seen_at") or ""),
            last_seen_at=str(props.get("last_seen_at") or ""),
            occurrence_count=_safe_int(props.get("occurrence_count")),
            redacted_context=_safe_redacted_context(props.get("redacted_context")),
            source_view_url=f"/admin/anomalies/{instance.euid}",
        )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_redacted_context(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, str) and not value.strip():
        return {}
    if isinstance(value, (list, tuple)) and not value:
        return {}
    return {"value": redact_context(value)}


def open_anomaly_repository(*, app_username: str):
    from bloom_lims.db import BLOOMdb3

    bdb = BLOOMdb3(app_username=app_username)
    return TapdbAnomalyRepository(bdb.session), bdb
