"""
BLOOM LIMS - Subject Management Module

This module provides helper functions for managing Subjects in BLOOM LIMS.
Subjects are logical aggregates that decisions apply to, spanning multiple objects.

Key concepts:
- Object (fact): A concrete thing (sample, container, fileset, etc.)
- Subject (decision scope): A logical aggregate that decisions apply to
- Anchor: The primary object that defines the subject
- Members: Additional objects associated with the subject

Relationship types:
- subject_anchor: Subject → Primary anchor object
- subject_member: Subject → Member/evidence objects
"""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Relationship type constants
RELATIONSHIP_SUBJECT_ANCHOR = "subject_anchor"
RELATIONSHIP_SUBJECT_MEMBER = "subject_member"

# Template mapping for subject kinds
SUBJECT_TEMPLATE_MAP = {
    "accession": "subject/generic/accession-subject/1.0",
    "analysis_bundle": "subject/generic/analysis-bundle-subject/1.0",
    "report": "subject/generic/report-subject/1.0",
    "generic": "subject/generic/generic-subject/1.0",
}


def generate_subject_key(subject_kind: str, anchor_euid: str) -> str:
    """
    Generate a stable, deterministic subject key.
    
    Args:
        subject_kind: The kind of subject (accession, analysis_bundle, report, generic)
        anchor_euid: The EUID of the anchor object
        
    Returns:
        A stable subject key in format "{subject_kind}:{anchor_euid}"
    """
    return f"{subject_kind}:{anchor_euid}"


def find_subject_by_key(bob, subject_key: str):
    """
    Find a subject by its stable subject_key.
    
    Args:
        bob: BloomObj instance
        subject_key: The subject_key to search for
        
    Returns:
        The subject instance if found, None otherwise
    """
    try:
        results = bob.session.query(bob.Base.classes.generic_instance).filter(
            bob.Base.classes.generic_instance.super_type == "subject",
            bob.Base.classes.generic_instance.is_deleted == False,
        ).all()
        
        for result in results:
            props = result.json_addl.get("properties", {})
            if props.get("subject_key") == subject_key:
                return result
        
        return None
    except Exception as e:
        logger.error(f"Error finding subject by key {subject_key}: {e}")
        return None


def get_subject_template_euid(bob, subject_kind: str) -> Optional[str]:
    """
    Get the template EUID for a given subject kind.
    
    Args:
        bob: BloomObj instance
        subject_kind: The kind of subject
        
    Returns:
        The template EUID if found, None otherwise
    """
    template_path = SUBJECT_TEMPLATE_MAP.get(subject_kind, SUBJECT_TEMPLATE_MAP["generic"])
    parts = template_path.split("/")
    if len(parts) != 4:
        logger.error(f"Invalid template path: {template_path}")
        return None
    
    super_type, btype, b_sub_type, version = parts
    
    try:
        templates = bob.query_template_by_component_v2(
            super_type=super_type,
            btype=btype,
            b_sub_type=b_sub_type,
            version=version
        )
        if templates:
            return templates[0].euid
        return None
    except Exception as e:
        logger.error(f"Error getting subject template: {e}")
        return None


def create_subject(
    bob,
    anchor_euid: str,
    subject_kind: str,
    subject_key: Optional[str] = None,
    extra_props: Dict[str, Any] = None,
    template_euid: Optional[str] = None,
) -> Optional[str]:
    """
    Create or find existing subject. Idempotent - returns existing if found.
    
    Args:
        bob: BloomObj instance
        anchor_euid: EUID of the anchor object
        subject_kind: Kind of subject (accession, analysis_bundle, report, generic)
        subject_key: Optional custom subject key. Defaults to "{subject_kind}:{anchor_euid}"
        extra_props: Additional properties to set on the subject
        template_euid: Optional template EUID override
        
    Returns:
        Subject EUID if successful, None otherwise
    """
    if extra_props is None:
        extra_props = {}
    
    # Generate subject_key if not provided
    if subject_key is None:
        subject_key = generate_subject_key(subject_kind, anchor_euid)
    
    # Check for existing subject (idempotency)
    existing = find_subject_by_key(bob, subject_key)
    if existing:
        logger.info(f"Subject already exists with key {subject_key}: {existing.euid}")
        return existing.euid
    
    # Get or validate template
    if template_euid is None:
        template_euid = get_subject_template_euid(bob, subject_kind)
    
    if template_euid is None:
        logger.error(f"No template found for subject kind: {subject_kind}")
        return None
    
    try:
        # Create the subject instance
        result = bob.create_instances(template_euid)
        if not result or not result[0]:
            logger.error("Failed to create subject instance")
            return None

        subject = result[0][0]

        # Update properties
        props = subject.json_addl.get("properties", {})
        props["subject_kind"] = subject_kind
        props["subject_key"] = subject_key
        props["anchor_euid"] = anchor_euid
        props["status"] = extra_props.get("status", "active")
        props["name"] = extra_props.get("name", f"Subject: {subject_key}")

        # Merge extra properties
        for key, value in extra_props.items():
            if key not in ["subject_kind", "subject_key", "anchor_euid"]:
                props[key] = value

        subject.json_addl["properties"] = props
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(subject, "json_addl")

        bob.session.commit()

        # Create anchor relationship
        link_subject_anchor(bob, subject.euid, anchor_euid)

        logger.info(f"Created subject {subject.euid} with key {subject_key}")
        return subject.euid

    except Exception as e:
        logger.error(f"Error creating subject: {e}")
        bob.session.rollback()
        return None


def link_subject_anchor(bob, subject_euid: str, anchor_euid: str) -> bool:
    """
    Create subject → anchor relationship edge.

    Args:
        bob: BloomObj instance
        subject_euid: EUID of the subject
        anchor_euid: EUID of the anchor object

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if relationship already exists
        subject = bob.get_by_euid(subject_euid)
        for lineage in subject.parent_of_lineages:
            if lineage.is_deleted:
                continue
            if (lineage.child_instance.euid == anchor_euid and
                lineage.relationship_type == RELATIONSHIP_SUBJECT_ANCHOR):
                logger.info(f"Anchor relationship already exists: {subject_euid} -> {anchor_euid}")
                return True

        bob.create_generic_instance_lineage_by_euids(
            subject_euid,
            anchor_euid,
            relationship_type=RELATIONSHIP_SUBJECT_ANCHOR
        )
        bob.session.commit()
        logger.info(f"Created anchor relationship: {subject_euid} -> {anchor_euid}")
        return True

    except Exception as e:
        logger.error(f"Error creating anchor relationship: {e}")
        bob.session.rollback()
        return False


def add_subject_members(bob, subject_euid: str, member_euids: List[str]) -> Dict[str, bool]:
    """
    Add subject → member relationship edges.

    Args:
        bob: BloomObj instance
        subject_euid: EUID of the subject
        member_euids: List of member object EUIDs

    Returns:
        Dict mapping member EUIDs to success status
    """
    results = {}
    subject = bob.get_by_euid(subject_euid)

    # Get existing member relationships
    existing_members = set()
    for lineage in subject.parent_of_lineages:
        if lineage.is_deleted:
            continue
        if lineage.relationship_type == RELATIONSHIP_SUBJECT_MEMBER:
            existing_members.add(lineage.child_instance.euid)

    for member_euid in member_euids:
        try:
            if member_euid in existing_members:
                logger.info(f"Member relationship already exists: {subject_euid} -> {member_euid}")
                results[member_euid] = True
                continue

            bob.create_generic_instance_lineage_by_euids(
                subject_euid,
                member_euid,
                relationship_type=RELATIONSHIP_SUBJECT_MEMBER
            )
            results[member_euid] = True
            logger.info(f"Created member relationship: {subject_euid} -> {member_euid}")

        except Exception as e:
            logger.error(f"Error adding member {member_euid}: {e}")
            results[member_euid] = False

    bob.session.commit()
    return results


def list_subjects_for_object(bob, object_euid: str) -> List[Dict[str, Any]]:
    """
    Find all subjects containing this object (as anchor or member).

    Args:
        bob: BloomObj instance
        object_euid: EUID of the object

    Returns:
        List of dicts with subject info: {euid, kind, role, status, subject_key}
    """
    subjects = []
    obj = bob.get_by_euid(object_euid)

    if not obj:
        return subjects

    # Templates don't have lineage relationships - only instances do
    if not hasattr(obj, 'child_of_lineages'):
        return subjects

    # Check child_of_lineages to find subjects where this object is a child
    for lineage in obj.child_of_lineages:
        if lineage.is_deleted:
            continue

        parent = lineage.parent_instance
        if parent.super_type != "subject":
            continue

        role = "unknown"
        if lineage.relationship_type == RELATIONSHIP_SUBJECT_ANCHOR:
            role = "anchor"
        elif lineage.relationship_type == RELATIONSHIP_SUBJECT_MEMBER:
            role = "member"

        props = parent.json_addl.get("properties", {})
        subjects.append({
            "euid": parent.euid,
            "kind": props.get("subject_kind", "unknown"),
            "role": role,
            "status": props.get("status", "unknown"),
            "subject_key": props.get("subject_key", ""),
            "name": props.get("name", parent.name),
        })

    return subjects


def list_members_for_subject(bob, subject_euid: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return anchor and members for a subject.

    Args:
        bob: BloomObj instance
        subject_euid: EUID of the subject

    Returns:
        Dict with keys 'anchor' and 'members', each containing list of object info
    """
    result = {"anchor": [], "members": []}
    subject = bob.get_by_euid(subject_euid)

    if not subject:
        return result

    # Templates don't have lineage relationships - only instances do
    if not hasattr(subject, 'parent_of_lineages'):
        return result

    for lineage in subject.parent_of_lineages:
        if lineage.is_deleted:
            continue

        child = lineage.child_instance
        obj_info = {
            "euid": child.euid,
            "name": child.json_addl.get("properties", {}).get("name", child.name),
            "btype": child.btype,
            "b_sub_type": child.b_sub_type,
            "super_type": child.super_type,
        }

        if lineage.relationship_type == RELATIONSHIP_SUBJECT_ANCHOR:
            result["anchor"].append(obj_info)
        elif lineage.relationship_type == RELATIONSHIP_SUBJECT_MEMBER:
            result["members"].append(obj_info)

    return result

