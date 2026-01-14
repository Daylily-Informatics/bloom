"""
BLOOM LIMS API v1 - Workflows Endpoints

Endpoints for workflow management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.get("/")
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_type: Optional[str] = Query(None, description="Filter by type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
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
async def get_workflow(euid: str, user: APIUser = Depends(require_api_auth)):
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
async def advance_workflow(
    euid: str,
    step_result: Optional[Dict[str, Any]] = None,
    user: APIUser = Depends(require_api_auth),
):
    """
    Advance a workflow to the next step.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.core.workflows import advance_workflow as do_advance

        bdb = BLOOMdb3(app_username=user.email)

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


@router.post("/", response_model=Dict[str, Any])
async def create_workflow(
    template_euid: str = Query(..., description="Template EUID to create workflow from"),
    name: Optional[str] = Query(None, description="Workflow name"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Create a new workflow from a template.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomWorkflow

        bdb = BLOOMdb3(app_username=user.email)
        bwf = BloomWorkflow(bdb)

        # Create workflow from template
        result = bwf.create_instances(template_euid)
        if not result or not result[0]:
            raise HTTPException(status_code=400, detail="Failed to create workflow from template")

        workflow = result[0][0]

        # Update name if provided
        if name:
            workflow.name = name
            bdb.session.commit()

        return {
            "success": True,
            "euid": workflow.euid,
            "uuid": str(workflow.uuid),
            "name": workflow.name,
            "status": workflow.bstatus,
            "message": "Workflow created successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{euid}", response_model=Dict[str, Any])
async def update_workflow(
    euid: str,
    name: Optional[str] = Query(None, description="New workflow name"),
    status: Optional[str] = Query(None, description="New workflow status"),
    json_addl: Optional[Dict[str, Any]] = None,
    user: APIUser = Depends(require_api_auth),
):
    """
    Update a workflow.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomWorkflow
        from sqlalchemy.orm.attributes import flag_modified

        bdb = BLOOMdb3(app_username=user.email)
        bwf = BloomWorkflow(bdb)

        workflow = bwf.get_by_euid(euid)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {euid}")

        if name is not None:
            workflow.name = name
        if status is not None:
            workflow.bstatus = status
        if json_addl is not None:
            existing = workflow.json_addl or {}
            existing.update(json_addl)
            workflow.json_addl = existing
            flag_modified(workflow, "json_addl")

        bdb.session.commit()

        return {
            "success": True,
            "euid": workflow.euid,
            "message": "Workflow updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating workflow {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}/steps", response_model=Dict[str, Any])
async def get_workflow_steps(euid: str, user: APIUser = Depends(require_api_auth)):
    """
    Get all steps for a workflow.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomWorkflow

        bdb = BLOOMdb3()
        bwf = BloomWorkflow(bdb)

        workflow = bwf.get_by_euid(euid)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {euid}")

        # Get workflow steps (children with btype containing 'step' or 'queue')
        steps = []
        for lineage in workflow.parent_of_lineages:
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child.btype in ["queue", "step"] or "step" in child.btype:
                steps.append({
                    "euid": child.euid,
                    "uuid": str(child.uuid),
                    "name": child.name,
                    "btype": child.btype,
                    "b_sub_type": child.b_sub_type,
                    "status": child.bstatus,
                    "order": child.json_addl.get("properties", {}).get("order", 0),
                })

        # Sort by order
        steps.sort(key=lambda x: x.get("order", 0))

        return {
            "workflow_euid": euid,
            "steps": steps,
            "count": len(steps),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow steps {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

