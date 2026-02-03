"""
BLOOM LIMS Content Module

This module contains content and sample management functionality for BLOOM LIMS.
Content objects represent physical or logical samples being processed.

For backward compatibility, this module re-exports functionality that was
originally in bloom_lims/bobjs.py.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
)


logger = logging.getLogger(__name__)


class BloomContentMixin:
    """
    Mixin class providing common content/sample functionality.
    """
    
    @property
    def sample_type(self) -> Optional[str]:
        """Get sample type from type or subtype."""
        if hasattr(self, 'subtype') and self.subtype:
            return self.subtype
        if hasattr(self, 'type'):
            return self.type
        return None
    
    @property
    def is_aliquot(self) -> bool:
        """Check if this is an aliquot of another sample."""
        if hasattr(self, 'json_addl') and self.json_addl:
            return self.json_addl.get('is_aliquot', False)
        return False
    
    @property
    def parent_sample_euid(self) -> Optional[str]:
        """Get parent sample EUID if this is an aliquot."""
        if hasattr(self, 'json_addl') and self.json_addl:
            return self.json_addl.get('parent_sample_euid')
        return None


def create_sample(
    session: Session,
    base,
    name: str,
    sample_type: str,
    sample_subtype: Optional[str] = None,
    template_euid: Optional[str] = None,
    json_addl: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """
    Create a new sample instance.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        name: Sample name
        sample_type: Type of sample
        sample_subtype: Subtype of sample (optional)
        template_euid: Template to create from (optional)
        json_addl: Additional JSON data (optional)
        **kwargs: Additional fields
        
    Returns:
        The created sample object
        
    Raises:
        ValidationError: If required fields are missing
        DatabaseError: If database operation fails
    """
    logger.debug(f"Creating sample: name={name}, type={sample_type}")
    
    if not name or not sample_type:
        raise ValidationError("name and sample_type are required")
    
    try:
        sample_class = getattr(base.classes, 'content_instance')
        
        sample = sample_class(
            name=name,
            type=sample_type.lower(),
            subtype=sample_subtype.lower() if sample_subtype else None,
            json_addl=json_addl or {},
            bstatus='active',
            category='content',
            polymorphic_discriminator='content_instance',
            **kwargs,
        )
        
        session.add(sample)
        session.flush()
        return sample
        
    except Exception as e:
        logger.error(f"Error creating sample: {e}")
        raise DatabaseError(f"Failed to create sample: {e}", operation="insert")


def get_sample_by_euid(
    session: Session,
    base,
    euid: str,
    include_deleted: bool = False,
) -> Optional[Any]:
    """
    Get a sample by its EUID.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        euid: Sample EUID
        include_deleted: Include soft-deleted samples
        
    Returns:
        The sample object or None
    """
    logger.debug(f"Looking up sample by EUID: {euid}")
    
    if not euid:
        return None
    
    try:
        query = session.query(base.classes.content_instance).filter(
            base.classes.content_instance.euid == euid.upper()
        )
        
        if not include_deleted:
            query = query.filter(
                base.classes.content_instance.is_deleted == False
            )
        
        return query.first()
        
    except Exception as e:
        logger.error(f"Error looking up sample {euid}: {e}")
        return None


def create_aliquot(
    session: Session,
    base,
    parent_sample: Any,
    name: Optional[str] = None,
    volume: Optional[float] = None,
    json_addl: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Create an aliquot from a parent sample.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        parent_sample: Parent sample object
        name: Aliquot name (defaults to parent name + suffix)
        volume: Aliquot volume
        json_addl: Additional JSON data

    Returns:
        The created aliquot object
    """
    logger.debug(f"Creating aliquot from sample: {parent_sample.euid}")

    # Count existing aliquots
    existing_aliquots = session.query(base.classes.content_instance).filter(
        base.classes.content_instance.json_addl.contains({'parent_sample_euid': parent_sample.euid})
    ).count()

    aliquot_name = name or f"{parent_sample.name}_ALQ{existing_aliquots + 1}"

    aliquot_json = {
        'is_aliquot': True,
        'parent_sample_euid': parent_sample.euid,
        'parent_sample_uuid': str(parent_sample.uuid),
        'aliquot_number': existing_aliquots + 1,
        'created_from_parent_at': datetime.utcnow().isoformat(),
    }

    if volume is not None:
        aliquot_json['volume'] = volume

    if json_addl:
        aliquot_json.update(json_addl)

    aliquot = create_sample(
        session=session,
        base=base,
        name=aliquot_name,
        sample_type=parent_sample.type,
        sample_subtype=parent_sample.subtype,
        json_addl=aliquot_json,
    )

    return aliquot


def get_sample_lineage(
    session: Session,
    base,
    sample_euid: str,
) -> Dict[str, Any]:
    """
    Get the lineage information for a sample.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        sample_euid: Sample EUID

    Returns:
        Dict with parent and children information
    """
    logger.debug(f"Getting lineage for sample: {sample_euid}")

    sample = get_sample_by_euid(session, base, sample_euid)
    if not sample:
        raise NotFoundError(
            f"Sample not found: {sample_euid}",
            resource_type="sample",
            resource_id=sample_euid
        )

    lineage = {
        'euid': sample.euid,
        'name': sample.name,
        'parent': None,
        'children': [],
    }

    # Get parent if aliquot
    if sample.json_addl and sample.json_addl.get('parent_sample_euid'):
        parent_euid = sample.json_addl['parent_sample_euid']
        parent = get_sample_by_euid(session, base, parent_euid)
        if parent:
            lineage['parent'] = {
                'euid': parent.euid,
                'name': parent.name,
            }

    # Get children (aliquots)
    try:
        children = session.query(base.classes.content_instance).filter(
            base.classes.content_instance.json_addl.contains({'parent_sample_euid': sample.euid})
        ).all()

        for child in children:
            lineage['children'].append({
                'euid': child.euid,
                'name': child.name,
            })
    except Exception as e:
        logger.warning(f"Error getting sample children: {e}")

    return lineage


# Re-export for backward compatibility
try:
    from bloom_lims.bobjs import BloomObj as _BloomObj
    BloomContent = _BloomObj
    BloomSample = _BloomObj
except ImportError:
    BloomContent = None
    BloomSample = None

