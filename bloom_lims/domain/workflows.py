"""
BLOOM LIMS Domain - Workflows

Workflow and WorkflowStep classes for managing laboratory workflows.
Extracted from bloom_lims/bobjs.py for better code organization.

Note: The full implementations of these classes remain in bobjs.py
for backward compatibility. This module provides class stubs that
inherit from the original implementations.
"""

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _get_bloom_workflow():
    """Get BloomWorkflow class from bobjs."""
    from bloom_lims.bobjs import BloomWorkflow as _BW
    return _BW


def _get_bloom_workflow_step():
    """Get BloomWorkflowStep class from bobjs."""
    from bloom_lims.bobjs import BloomWorkflowStep as _BWS
    return _BWS


class BloomWorkflow:
    """
    Workflow class for managing laboratory workflows.
    
    This class provides workflow management functionality including:
    - Creating workflows from templates
    - Managing workflow steps
    - Executing workflow actions
    - Tracking workflow status
    
    The actual implementation is in bobjs.py. This class provides
    a clean interface and documentation.
    """
    
    _actual_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._actual_class is None:
            cls._actual_class = _get_bloom_workflow()
        # Return an instance of the actual class from bobjs
        return cls._actual_class(*args, **kwargs)
    
    @classmethod
    def get_workflow_by_euid(cls, bdb, workflow_euid: str):
        """
        Get a workflow by its EUID with sorted steps.
        
        Args:
            bdb: Database connection
            workflow_euid: Workflow EUID
            
        Returns:
            Workflow object with workflow_steps_sorted attribute
        """
        instance = cls(bdb)
        return instance.get_sorted_euid(workflow_euid)


class BloomWorkflowStep:
    """
    Workflow Step class for managing individual workflow steps.
    
    This class provides step-specific functionality including:
    - Creating workflow steps from templates
    - Executing step-specific actions
    - Managing step status and transitions
    - Handling data capture for steps
    
    The actual implementation is in bobjs.py. This class provides
    a clean interface and documentation.
    """
    
    _actual_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._actual_class is None:
            cls._actual_class = _get_bloom_workflow_step()
        # Return an instance of the actual class from bobjs
        return cls._actual_class(*args, **kwargs)


# Convenience functions for workflow operations

def create_workflow(bdb, template_euid: str) -> Any:
    """
    Create a new workflow from a template.
    
    Args:
        bdb: Database connection
        template_euid: Template EUID to create workflow from
        
    Returns:
        Created workflow object
    """
    wf = BloomWorkflow(bdb)
    return wf.create_empty_workflow(template_euid)


def get_workflow_steps(bdb, workflow_euid: str) -> List[Any]:
    """
    Get sorted workflow steps for a workflow.
    
    Args:
        bdb: Database connection
        workflow_euid: Workflow EUID
        
    Returns:
        List of workflow steps sorted by step_number
    """
    wf = BloomWorkflow(bdb)
    workflow = wf.get_sorted_euid(workflow_euid)
    return getattr(workflow, 'workflow_steps_sorted', [])


def execute_workflow_action(
    bdb,
    target_euid: str,
    action_name: str,
    action_group: str,
    action_data: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Execute an action on a workflow or workflow step.
    
    Args:
        bdb: Database connection
        target_euid: Target object EUID (workflow or step)
        action_name: Name of action to execute
        action_group: Action group name
        action_data: Action parameters
        
    Returns:
        Action result
    """
    # Determine if target is workflow or workflow step
    obj = BloomWorkflow(bdb)
    target = obj.get_by_euid(target_euid)
    
    if not target:
        raise ValueError(f"Target not found: {target_euid}")
    
    if target.super_type == "workflow":
        return obj.do_action(target_euid, action_name, action_group, action_data or {})
    elif target.super_type == "workflow_step":
        step_obj = BloomWorkflowStep(bdb)
        return step_obj.do_action(target_euid, action_name, action_group, action_data or {})
    else:
        raise ValueError(f"Target is not a workflow or workflow step: {target.super_type}")


def advance_workflow_step(bdb, workflow_euid: str, step_data: Optional[Dict] = None) -> Any:
    """
    Advance a workflow to the next step.
    
    Args:
        bdb: Database connection
        workflow_euid: Workflow EUID
        step_data: Data to record for current step
        
    Returns:
        Updated workflow object
    """
    wf = BloomWorkflow(bdb)
    workflow = wf.get_sorted_euid(workflow_euid)
    
    # Find current step and mark complete
    steps = getattr(workflow, 'workflow_steps_sorted', [])
    for step in steps:
        if step.bstatus in ['pending', 'in_progress']:
            step.bstatus = 'completed'
            if step_data:
                step.json_addl = step.json_addl or {}
                step.json_addl['step_result'] = step_data
            wf.session.commit()
            break
    
    return wf.get_sorted_euid(workflow_euid)

