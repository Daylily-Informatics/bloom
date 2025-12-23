"""
BLOOM LIMS Domain - Equipment

Equipment and HealthEvent classes for managing lab equipment.
Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def _get_base_class():
    """Get BloomObj base class lazily."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj


class BloomEquipment:
    """
    Equipment class for managing lab equipment and instruments.
    
    This class extends BloomObj to provide equipment-specific functionality
    including tracking maintenance, calibration, and usage.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_equipment(self, template_euid: str):
        """Create empty equipment from a template."""
        return self.create_instances(template_euid)
    
    def record_maintenance(
        self,
        equipment_euid: str,
        maintenance_type: str,
        performed_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Any:
        """
        Record a maintenance event for equipment.
        
        Args:
            equipment_euid: Equipment EUID
            maintenance_type: Type of maintenance performed
            performed_by: Who performed the maintenance
            notes: Additional notes
            
        Returns:
            Updated equipment object
        """
        from bloom_lims.bobjs import get_datetime_string
        
        equipment = self.get_by_euid(equipment_euid)
        if not equipment:
            raise ValueError(f"Equipment not found: {equipment_euid}")
        
        equipment.json_addl = equipment.json_addl or {}
        maintenance_records = equipment.json_addl.get("maintenance_records", [])
        
        maintenance_records.append({
            "type": maintenance_type,
            "performed_at": get_datetime_string(),
            "performed_by": performed_by,
            "notes": notes,
        })
        
        equipment.json_addl["maintenance_records"] = maintenance_records
        equipment.json_addl["last_maintenance"] = get_datetime_string()
        
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(equipment, "json_addl")
        self.session.commit()
        
        return equipment
    
    def record_calibration(
        self,
        equipment_euid: str,
        calibrated_by: Optional[str] = None,
        certificate_number: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Record a calibration event for equipment.
        
        Args:
            equipment_euid: Equipment EUID
            calibrated_by: Who performed calibration
            certificate_number: Calibration certificate number
            parameters: Calibration parameters
            
        Returns:
            Updated equipment object
        """
        from bloom_lims.bobjs import get_datetime_string
        
        equipment = self.get_by_euid(equipment_euid)
        if not equipment:
            raise ValueError(f"Equipment not found: {equipment_euid}")
        
        equipment.json_addl = equipment.json_addl or {}
        calibration_records = equipment.json_addl.get("calibration_records", [])
        
        calibration_records.append({
            "calibrated_at": get_datetime_string(),
            "calibrated_by": calibrated_by,
            "certificate_number": certificate_number,
            "parameters": parameters or {},
        })
        
        equipment.json_addl["calibration_records"] = calibration_records
        equipment.json_addl["last_calibration"] = get_datetime_string()
        
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(equipment, "json_addl")
        self.session.commit()
        
        return equipment


class BloomHealthEvent:
    """
    Health Event class for tracking system health events.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_event(self):
        """Create a new health event."""
        new_event = self.create_instance(
            self.query_template_by_component_v2(
                "health_event", "generic", "health-event", "1.0"
            )[0].euid
        )
        self.session.commit()
        return new_event

