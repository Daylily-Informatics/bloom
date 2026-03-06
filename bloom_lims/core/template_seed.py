"""
Supplemental template seeding for Bloom legacy template configs.

TapDB's built-in seed command only loads its core/workflow template set. Bloom
still ships additional template definitions in `bloom_lims/config` using the
legacy file format. This module loads those templates and upserts them into
`generic_template` through the TapDB-backed Bloom adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, Optional

from daylily_tapdb.sequences import ensure_instance_prefix_sequence

from bloom_lims.db import BLOOMdb3


KNOWN_POLYMORPHIC_CATEGORIES = {
    "generic",
    "workflow",
    "workflow_step",
    "container",
    "content",
    "equipment",
    "data",
    "test_requisition",
    "actor",
    "action",
    "health_event",
    "file",
    "subject",
}


@dataclass(frozen=True)
class TemplateRecord:
    category: str
    type_name: str
    subtype: str
    version: str
    name: str
    polymorphic_discriminator: str
    instance_prefix: str
    instance_polymorphic_identity: str
    bstatus: str
    is_singleton: bool
    json_addl: dict


@dataclass(frozen=True)
class SeedSummary:
    templates_loaded: int
    inserted: int
    updated: int
    prefixes_ensured: int


def _default_config_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "config"


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _normalize_prefix(prefix: object) -> str:
    if prefix is None:
        return ""
    normalized = str(prefix).strip().upper()
    return normalized if normalized.isalpha() else ""


def _template_polymorphic_discriminator(category: str) -> str:
    if category in KNOWN_POLYMORPHIC_CATEGORIES:
        return f"{category}_template"
    return "generic_template"


def _instance_polymorphic_identity(category: str) -> str:
    if category in KNOWN_POLYMORPHIC_CATEGORIES:
        return f"{category}_instance"
    return "generic_instance"


def _load_metadata_prefixes(category_dir: Path) -> Dict[str, str]:
    metadata_path = category_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}

    euid_prefixes = payload.get("euid_prefixes", {})
    if not isinstance(euid_prefixes, dict):
        return {}

    result: Dict[str, str] = {}
    for key, value in euid_prefixes.items():
        normalized = _normalize_prefix(value)
        if normalized:
            result[str(key)] = normalized
    return result


def _resolve_instance_prefix(
    metadata_prefixes: Dict[str, str],
    type_name: str,
    subtype: str,
    template_data: dict,
) -> str:
    direct = _normalize_prefix(template_data.get("instance_prefix"))
    if direct:
        return direct

    for key in (type_name, subtype, "default"):
        if key in metadata_prefixes:
            value = _normalize_prefix(metadata_prefixes.get(key))
            if value:
                return value

    return "GX"


def _iter_legacy_template_records(config_dir: Path) -> Iterator[TemplateRecord]:
    for category_dir in sorted(config_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue

        category = category_dir.name
        metadata_prefixes = _load_metadata_prefixes(category_dir)

        for json_file in sorted(category_dir.glob("*.json")):
            if json_file.name == "metadata.json":
                continue

            type_name = json_file.stem
            with open(json_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if not isinstance(payload, dict):
                continue

            for subtype, versions in payload.items():
                if not isinstance(versions, dict):
                    continue
                for version, template_data in versions.items():
                    if not isinstance(template_data, dict):
                        continue

                    code = f"{category}/{type_name}/{subtype}/{version}"
                    description = str(template_data.get("description") or code)
                    instance_prefix = _resolve_instance_prefix(
                        metadata_prefixes=metadata_prefixes,
                        type_name=type_name,
                        subtype=str(subtype),
                        template_data=template_data,
                    )

                    yield TemplateRecord(
                        category=category,
                        type_name=type_name,
                        subtype=str(subtype),
                        version=str(version),
                        name=description,
                        polymorphic_discriminator=_template_polymorphic_discriminator(category),
                        instance_prefix=instance_prefix,
                        instance_polymorphic_identity=_instance_polymorphic_identity(category),
                        bstatus=str(template_data.get("bstatus") or "active"),
                        is_singleton=_coerce_bool(
                            template_data.get("is_singleton", template_data.get("singleton"))
                        ),
                        json_addl=template_data,
                    )


def _ensure_instance_prefix_sequence(session, prefix: str) -> None:
    normalized = _normalize_prefix(prefix)
    if not normalized:
        return

    ensure_instance_prefix_sequence(session, normalized)


def seed_bloom_templates(config_dir: Optional[Path] = None, *, overwrite: bool = False) -> SeedSummary:
    """
    Upsert Bloom legacy templates into TAPDB generic_template.

    Returns summary counts for inserted/updated templates and ensured prefixes.
    """
    cfg_dir = Path(config_dir) if config_dir else _default_config_dir()
    if not cfg_dir.exists():
        raise FileNotFoundError(f"Bloom template config directory not found: {cfg_dir}")

    records = list(_iter_legacy_template_records(cfg_dir))
    if not records:
        return SeedSummary(templates_loaded=0, inserted=0, updated=0, prefixes_ensured=0)

    bdb = BLOOMdb3(app_username="bloom-template-seed")
    inserted = 0
    updated = 0
    prefixes: set[str] = set()

    try:
        session = bdb.session
        classes = bdb.Base.classes
        generic_template_cls = classes.generic_template

        for record in records:
            prefixes.add(record.instance_prefix)
            existing = (
                session.query(generic_template_cls)
                .filter(
                    generic_template_cls.category == record.category,
                    generic_template_cls.type == record.type_name,
                    generic_template_cls.subtype == record.subtype,
                    generic_template_cls.version == record.version,
                )
                .one_or_none()
            )

            if existing is None:
                model_cls = getattr(
                    classes, f"{record.category}_template", generic_template_cls
                )
                new_template = model_cls(
                    name=record.name,
                    polymorphic_discriminator=record.polymorphic_discriminator,
                    category=record.category,
                    type=record.type_name,
                    subtype=record.subtype,
                    version=record.version,
                    instance_prefix=record.instance_prefix,
                    instance_polymorphic_identity=record.instance_polymorphic_identity,
                    bstatus=record.bstatus,
                    is_singleton=record.is_singleton,
                    is_deleted=False,
                    json_addl=record.json_addl,
                )
                session.add(new_template)
                inserted += 1
                continue

            if not overwrite:
                # Existing templates are intentionally left unchanged by
                # default. Some legacy local dev databases carried mixed
                # typing; mutating rows could fail in those environments.
                # Use overwrite=True (CLI: `bloom db seed --overwrite`) when
                # you explicitly want config-driven updates.
                continue

            # Minimal overwrite: config-driven json_addl is the main contract
            # for templates. Keep other fields aligned too.
            changed = False
            if existing.name != record.name:
                existing.name = record.name
                changed = True
            if getattr(existing, "instance_prefix", None) != record.instance_prefix:
                existing.instance_prefix = record.instance_prefix
                changed = True
            if getattr(existing, "instance_polymorphic_identity", None) != record.instance_polymorphic_identity:
                existing.instance_polymorphic_identity = record.instance_polymorphic_identity
                changed = True
            if getattr(existing, "bstatus", None) != record.bstatus:
                existing.bstatus = record.bstatus
                changed = True
            if getattr(existing, "is_singleton", None) != record.is_singleton:
                existing.is_singleton = record.is_singleton
                changed = True
            if getattr(existing, "is_deleted", None):
                existing.is_deleted = False
                changed = True
            if getattr(existing, "json_addl", None) != record.json_addl:
                existing.json_addl = record.json_addl
                changed = True
            if changed:
                updated += 1

        for prefix in sorted(prefixes):
            _ensure_instance_prefix_sequence(session, prefix)

        session.commit()
    except Exception:
        bdb.session.rollback()
        raise
    finally:
        bdb.close()

    return SeedSummary(
        templates_loaded=len(records),
        inserted=inserted,
        updated=updated,
        prefixes_ensured=len(prefixes),
    )
