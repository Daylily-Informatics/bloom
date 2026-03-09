"""
BLOOM LIMS Workflows Module

This module contains workflow and workflow step functionality for BLOOM LIMS.
Workflows manage the processing pipeline for samples and other lab objects.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    WorkflowError,
    DatabaseError,
)


logger = logging.getLogger(__name__)


def _workflow_step_number(step: Any) -> Optional[int]:
    json_addl = step.json_addl if isinstance(step.json_addl, dict) else {}
    properties = json_addl.get('properties', {})
    raw_value = properties.get('step_number', json_addl.get('step_number'))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _workflow_step_sort_key(step: Any) -> tuple[int, str]:
    step_number = _workflow_step_number(step)
    return (step_number if step_number is not None else 10**9, getattr(step, 'euid', ''))


def _attach_step_to_workflow(session: Session, base, workflow: Any, step: Any) -> None:
    lineage_class = getattr(base.classes, 'generic_instance_lineage')
    parent_category = getattr(workflow, 'category', None) or 'workflow'
    child_category = getattr(step, 'category', None) or 'workflow_step'
    lineage = lineage_class(
        parent_instance_uid=workflow.uid,
        child_instance_uid=step.uid,
        name=f"{workflow.name} :: {step.name}",
        type=workflow.type,
        subtype=workflow.subtype,
        version=workflow.version,
        json_addl=workflow.json_addl or {},
        bstatus=workflow.bstatus,
        category='generic',
        parent_type=(
            f"{parent_category}:{workflow.type}:{workflow.subtype}:{workflow.version}"
        ),
        child_type=(
            f"{child_category}:{step.type}:{step.subtype}:{step.version}"
        ),
        polymorphic_discriminator='generic_instance_lineage',
        relationship_type='generic',
    )
    session.add(lineage)


class BloomWorkflowMixin:
    """
    Mixin class providing common workflow functionality.
    """
    
    @property
    def is_complete(self) -> bool:
        """Check if workflow is complete."""
        return hasattr(self, 'bstatus') and self.bstatus == 'complete'
    
    @property
    def is_in_progress(self) -> bool:
        """Check if workflow is in progress."""
        return hasattr(self, 'bstatus') and self.bstatus == 'in_progress'
    
    @property
    def current_step_number(self) -> Optional[int]:
        """Get current step number from json_addl."""
        if hasattr(self, 'json_addl') and self.json_addl:
            return self.json_addl.get('current_step')
        return None


class BloomWorkflowStepMixin:
    """
    Mixin class providing common workflow step functionality.
    """
    
    @property
    def is_completed(self) -> bool:
        """Check if step is completed."""
        return hasattr(self, 'bstatus') and self.bstatus == 'completed'
    
    @property
    def is_pending(self) -> bool:
        """Check if step is pending."""
        return hasattr(self, 'bstatus') and self.bstatus == 'pending'
    
    @property
    def is_skipped(self) -> bool:
        """Check if step was skipped."""
        return hasattr(self, 'bstatus') and self.bstatus == 'skipped'


def create_workflow(
    session: Session,
    base,
    name: str,
    workflow_type: str,
    steps: Optional[List[Dict[str, Any]]] = None,
    template_euid: Optional[str] = None,
    json_addl: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """
    Create a new workflow.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        name: Workflow name
        workflow_type: Type of workflow
        steps: List of step definitions (optional)
        template_euid: Template to create from (optional)
        json_addl: Additional JSON data (optional)
        **kwargs: Additional fields
        
    Returns:
        The created workflow object
        
    Raises:
        ValidationError: If required fields are missing
        WorkflowError: If workflow creation fails
    """
    logger.debug(f"Creating workflow: name={name}, type={workflow_type}")
    
    if not name or not workflow_type:
        raise ValidationError("name and workflow_type are required")
    
    try:
        workflow_class = getattr(base.classes, 'workflow_instance')
        
        workflow = workflow_class(
            name=name,
            type=workflow_type.lower(),
            json_addl=json_addl or {},
            bstatus='pending',
            category='workflow',
            polymorphic_discriminator='workflow_instance',
            **kwargs,
        )
        
        session.add(workflow)
        session.flush()
        
        # Create steps if provided
        if steps:
            for i, step_def in enumerate(steps, 1):
                create_workflow_step(
                    session=session,
                    base=base,
                    workflow=workflow,
                    step_number=i,
                    **step_def,
                )
        
        return workflow
        
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        raise WorkflowError(f"Failed to create workflow: {e}", action="create")


def create_workflow_step(
    session: Session,
    base,
    workflow: Any,
    step_number: int,
    name: str,
    step_type: str = "standard",
    json_addl: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """
    Create a workflow step.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        workflow: Parent workflow object
        step_number: Step order number
        name: Step name
        step_type: Type of step
        json_addl: Additional JSON data
        **kwargs: Additional fields
        
    Returns:
        The created step object
    """
    logger.debug(f"Creating workflow step: {name} (#{step_number})")

    try:
        step_class = getattr(base.classes, 'workflow_step_instance')
        step_json = dict(json_addl or {})
        properties = dict(step_json.get('properties') or {})
        properties.setdefault('step_number', step_number)
        step_json['properties'] = properties

        step = step_class(
            name=name,
            type=step_type.lower(),
            json_addl=step_json,
            bstatus='pending',
            category='workflow_step',
            polymorphic_discriminator='workflow_step_instance',
            **kwargs,
        )

        session.add(step)
        session.flush()
        _attach_step_to_workflow(session, base, workflow, step)
        session.flush()
        return step

    except Exception as e:
        logger.error(f"Error creating workflow step: {e}")
        raise WorkflowError(
            f"Failed to create workflow step: {e}",
            workflow_euid=getattr(workflow, 'euid', None),
            action="create_step"
        )


def get_workflow_by_euid(
    session: Session,
    base,
    euid: str,
    include_steps: bool = True,
) -> Optional[Any]:
    """
    Get a workflow by its EUID.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        euid: Workflow EUID
        include_steps: Whether to load steps

    Returns:
        The workflow object or None
    """
    logger.debug(f"Looking up workflow by EUID: {euid}")

    if not euid:
        return None

    try:
        workflow = session.query(base.classes.workflow_instance).filter(
            base.classes.workflow_instance.euid == euid.upper()
        ).first()

        return workflow

    except Exception as e:
        logger.error(f"Error looking up workflow {euid}: {e}")
        return None


def get_workflow_steps(
    session: Session,
    base,
    workflow_euid: str,
    status: Optional[str] = None,
) -> List[Any]:
    """
    Get steps for a workflow.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        workflow_euid: Parent workflow EUID
        status: Filter by status (optional)

    Returns:
        List of workflow step objects
    """
    logger.debug(f"Getting steps for workflow: {workflow_euid}")

    try:
        workflow = get_workflow_by_euid(session, base, workflow_euid, include_steps=False)
        if not workflow:
            return []

        steps = []
        for lineage in getattr(workflow, 'parent_of_lineages', []) or []:
            if getattr(lineage, 'is_deleted', False):
                continue

            step = getattr(lineage, 'child_instance', None)
            if step is None or getattr(step, 'is_deleted', False):
                continue
            if getattr(step, 'category', None) != 'workflow_step':
                continue
            if status and getattr(step, 'bstatus', None) != status:
                continue
            steps.append(step)

        steps.sort(key=_workflow_step_sort_key)
        return steps

    except Exception as e:
        logger.error(f"Error getting workflow steps: {e}")
        return []


def advance_workflow(
    session: Session,
    base,
    workflow_euid: str,
    step_result: Optional[Dict[str, Any]] = None,
    completed_by: Optional[str] = None,
) -> Any:
    """
    Advance a workflow to the next step.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        workflow_euid: Workflow EUID
        step_result: Result data from current step
        completed_by: User who completed the step

    Returns:
        Updated workflow object

    Raises:
        WorkflowError: If workflow cannot be advanced
    """
    logger.debug(f"Advancing workflow: {workflow_euid}")

    workflow = get_workflow_by_euid(session, base, workflow_euid)
    if not workflow:
        raise NotFoundError(
            f"Workflow not found: {workflow_euid}",
            resource_type="workflow",
            resource_id=workflow_euid
        )

    if workflow.bstatus == 'complete':
        raise WorkflowError(
            "Workflow is already complete",
            workflow_euid=workflow_euid,
            action="advance"
        )

    if not isinstance(workflow.json_addl, dict):
        workflow.json_addl = {}

    # Get current step and mark as complete
    steps = get_workflow_steps(session, base, workflow.euid, status='pending')
    if not steps:
        workflow.bstatus = 'complete'
        workflow.json_addl['completed_at'] = datetime.now(UTC).isoformat()
        session.flush()
        return workflow

    # Complete current step
    current_step = steps[0]
    current_step.bstatus = 'completed'
    if not isinstance(current_step.json_addl, dict):
        current_step.json_addl = {}
    current_step.json_addl['completed_at'] = datetime.now(UTC).isoformat()
    if completed_by:
        current_step.json_addl['completed_by'] = completed_by
    if step_result:
        current_step.json_addl['result'] = step_result

    # Check if more steps remain
    remaining_steps = get_workflow_steps(session, base, workflow.euid, status='pending')
    if not remaining_steps:
        workflow.bstatus = 'complete'
        workflow.json_addl['completed_at'] = datetime.now(UTC).isoformat()
    else:
        workflow.bstatus = 'in_progress'
        workflow.json_addl['current_step'] = _workflow_step_number(remaining_steps[0]) or 1

    session.flush()
    return workflow


# Export workflow object aliases via BloomObj.
try:
    from bloom_lims.bobjs import BloomObj as _BloomObj
    BloomWorkflow = _BloomObj
    BloomWorkflowStep = _BloomObj
except ImportError:
    BloomWorkflow = None
    BloomWorkflowStep = None
