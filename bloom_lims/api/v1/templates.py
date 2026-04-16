"""
BLOOM LIMS API v1 - Templates Endpoints

Endpoints for template management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.config import get_settings
from bloom_lims.template_identity import (
    template_category_filter,
    template_semantic_category,
)
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/templates", tags=["Templates"])


def _tapdb_domain_code() -> str:
    return str(get_settings().tapdb.domain_code).strip().upper()


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/", response_model=Dict[str, Any])
async def list_templates(
    domain_code: str = Query(..., description="Meridian domain code"),
    category: Optional[str] = Query(None, description="Filter by category (container, content, equipment)"),
    type: Optional[str] = Query(None, description="Filter by type"),
    subtype: Optional[str] = Query(None, description="Filter by subtype"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List available templates."""
    try:
        bdb = get_bdb(user.email)
        domain_code = _tapdb_domain_code()

        query = bdb.session.query(bdb.Base.classes.generic_template)
        query = query.filter(
            bdb.Base.classes.generic_template.domain_code == domain_code
        )

        if category:
            category_filter = template_category_filter(
                bdb.Base.classes.generic_template, category
            )
            if category_filter is not None:
                query = query.filter(category_filter)
        if type:
            query = query.filter(bdb.Base.classes.generic_template.type == type.lower())
        if subtype:
            query = query.filter(bdb.Base.classes.generic_template.subtype == subtype.lower())

        query = query.filter(bdb.Base.classes.generic_template.is_deleted == False)

        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()

        return {
            "items": [
                {
                    "euid": t.euid,
                    "name": t.name,
                    "category": template_semantic_category(t),
                    "type": t.type,
                    "subtype": t.subtype,
                    "polymorphic_discriminator": t.polymorphic_discriminator,
                }
                for t in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_template(
    euid: str,
    domain_code: str = Query(..., description="Meridian domain code"),
    user: APIUser = Depends(require_api_auth),
):
    """Get a template by EUID."""
    try:
        bdb = get_bdb(user.email)
        domain_code = _tapdb_domain_code()

        template = bdb.session.query(bdb.Base.classes.generic_template).filter(
            bdb.Base.classes.generic_template.euid == euid,
            bdb.Base.classes.generic_template.domain_code == domain_code,
        ).first()

        if not template:
            raise HTTPException(status_code=404, detail=f"Template not found: {euid}")

        return {
            "euid": template.euid,
            "name": template.name,
            "category": template_semantic_category(template),
            "type": template.type,
            "subtype": template.subtype,
            "polymorphic_discriminator": template.polymorphic_discriminator,
            "json_addl": template.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-category/{category}", response_model=Dict[str, Any])
async def list_templates_by_category(
    category: str,
    domain_code: str = Query(..., description="Meridian domain code"),
    user: APIUser = Depends(require_api_auth),
):
    """List templates by category (container, content, equipment, workflow)."""
    try:
        bdb = get_bdb(user.email)
        domain_code = _tapdb_domain_code()

        query = bdb.session.query(bdb.Base.classes.generic_template).filter(
            bdb.Base.classes.generic_template.domain_code == domain_code,
            bdb.Base.classes.generic_template.is_deleted == False,
        )
        category_filter = template_category_filter(
            bdb.Base.classes.generic_template, category
        )
        if category_filter is not None:
            query = query.filter(category_filter)

        items = query.all()
        resolved_category = template_semantic_category(items[0]) if items else category

        return {
            "category": resolved_category,
            "templates": [
                {
                    "euid": t.euid,
                    "name": t.name,
                    "type": t.type,
                    "subtype": t.subtype,
                }
                for t in items
            ],
            "count": len(items),
        }
    except Exception as e:
        logger.error(f"Error listing templates by category {category}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
