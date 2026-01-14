"""
BLOOM LIMS API v1 - Templates Endpoints

Endpoints for template management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/templates", tags=["Templates"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/", response_model=Dict[str, Any])
async def list_templates(
    super_type: Optional[str] = Query(None, description="Filter by super_type (container, content, equipment)"),
    btype: Optional[str] = Query(None, description="Filter by btype"),
    b_sub_type: Optional[str] = Query(None, description="Filter by b_sub_type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List available templates."""
    try:
        bdb = get_bdb(user.email)
        
        query = bdb.session.query(bdb.Base.classes.generic_template)
        
        if super_type:
            query = query.filter(bdb.Base.classes.generic_template.super_type == super_type.lower())
        if btype:
            query = query.filter(bdb.Base.classes.generic_template.btype == btype.lower())
        if b_sub_type:
            query = query.filter(bdb.Base.classes.generic_template.b_sub_type == b_sub_type.lower())
        
        query = query.filter(bdb.Base.classes.generic_template.is_deleted == False)
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "euid": t.euid,
                    "uuid": str(t.uuid),
                    "name": t.name,
                    "super_type": t.super_type,
                    "btype": t.btype,
                    "b_sub_type": t.b_sub_type,
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
async def get_template(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get a template by EUID."""
    try:
        bdb = get_bdb(user.email)
        
        template = bdb.session.query(bdb.Base.classes.generic_template).filter(
            bdb.Base.classes.generic_template.euid == euid
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail=f"Template not found: {euid}")
        
        return {
            "euid": template.euid,
            "uuid": str(template.uuid),
            "name": template.name,
            "super_type": template.super_type,
            "btype": template.btype,
            "b_sub_type": template.b_sub_type,
            "polymorphic_discriminator": template.polymorphic_discriminator,
            "json_addl": template.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-type/{super_type}", response_model=Dict[str, Any])
async def list_templates_by_super_type(
    super_type: str,
    user: APIUser = Depends(require_api_auth),
):
    """List templates by super_type (container, content, equipment, workflow)."""
    try:
        bdb = get_bdb(user.email)
        
        query = bdb.session.query(bdb.Base.classes.generic_template).filter(
            bdb.Base.classes.generic_template.super_type == super_type.lower(),
            bdb.Base.classes.generic_template.is_deleted == False,
        )
        
        items = query.all()
        
        return {
            "super_type": super_type,
            "templates": [
                {
                    "euid": t.euid,
                    "name": t.name,
                    "btype": t.btype,
                    "b_sub_type": t.b_sub_type,
                }
                for t in items
            ],
            "count": len(items),
        }
    except Exception as e:
        logger.error(f"Error listing templates by super_type {super_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

