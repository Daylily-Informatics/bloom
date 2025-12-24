"""
BLOOM LIMS API v1 - Workflows Endpoints

Endpoints for workflow management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.get("/")
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_type: Optional[str] = Query(None, description="Filter by type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """
    List workflows with optional filters.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        
        bdb = BLOOMdb3()
        
        query = bdb.session.query(bdb.Base.classes.workflow_instance)
        
        if status:
            query = query.filter(bdb.Base.classes.workflow_instance.bstatus == status)
        if workflow_type:
            query = query.filter(bdb.Base.classes.workflow_instance.btype == workflow_type.lower())
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "euid": wf.euid,
                    "uuid": str(wf.uuid),
                    "name": wf.name,
                    "type": wf.btype,
                    "status": wf.bstatus,
                }
                for wf in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
        
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_workflow(euid: str):
    """
    Get a workflow by EUID.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.core.workflows import get_workflow_by_euid
        
        bdb = BLOOMdb3()
        
        workflow = get_workflow_by_euid(bdb.session, bdb.Base, euid)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {euid}")
        
        return {
            "euid": workflow.euid,
            "uuid": str(workflow.uuid),
            "name": workflow.name,
            "type": workflow.btype,
            "status": workflow.bstatus,
            "json_addl": workflow.json_addl,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{euid}/advance")
async def advance_workflow(euid: str, step_result: Optional[Dict[str, Any]] = None):
    """
    Advance a workflow to the next step.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.core.workflows import advance_workflow as do_advance
        
        bdb = BLOOMdb3()
        
        workflow = do_advance(
            session=bdb.session,
            base=bdb.Base,
            workflow_euid=euid,
            step_result=step_result,
        )
        
        bdb.session.commit()
        
        return {
            "success": True,
            "euid": workflow.euid,
            "status": workflow.bstatus,
            "message": "Workflow advanced successfully",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error advancing workflow {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

