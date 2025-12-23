"""
BLOOM LIMS Domain - Content

Content classes for samples, specimens, reagents, pools, and controls.
Extracted from bloom_lims/bobjs.py for better code organization.
"""

import random
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def _get_base_class():
    """Get BloomObj base class lazily."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj


class BloomContent:
    """
    Content class for managing samples, specimens, and other content objects.
    
    This class extends BloomObj to provide content-specific functionality.
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

    def create_empty_content(self, template_euid: str):
        """
        Create empty content from a template.

        Args:
            template_euid: Template EUID to create content from

        Returns:
            Created content object(s)
        """
        return self.create_instances(template_euid)
    
    def create_sample(self, template_euid: str, properties: Optional[Dict[str, Any]] = None):
        """
        Create a sample from a template with optional properties.
        
        Args:
            template_euid: Template EUID for the sample
            properties: Additional properties to set on the sample
            
        Returns:
            Created sample object
        """
        json_addl_overrides = {}
        if properties:
            json_addl_overrides["properties"] = properties
        return self.create_instance(template_euid, json_addl_overrides)
    
    def create_specimen(self, template_euid: str, properties: Optional[Dict[str, Any]] = None):
        """
        Create a specimen from a template with optional properties.
        
        Args:
            template_euid: Template EUID for the specimen
            properties: Additional properties to set
            
        Returns:
            Created specimen object
        """
        json_addl_overrides = {}
        if properties:
            json_addl_overrides["properties"] = properties
        return self.create_instance(template_euid, json_addl_overrides)


class BloomReagent(BloomContent):
    """
    Specialized content class for reagent management.
    
    Provides reagent-specific operations like creating reagent plates.
    """
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_rgnt_24w_plate_TEST(self, rg_code: str = "idt-probes-rare-mendelian") -> str:
        """
        Create a test reagent plate with 24 wells.
        
        This is a test/example method demonstrating reagent plate creation.
        
        Args:
            rg_code: Reagent code for the probe type
            
        Returns:
            EUID of the created plate
        """
        containers = self.create_instances(
            self.query_template_by_component_v2(
                "container", "plate", "fixed-plate-24", "1.0"
            )[0].euid
        )

        plate = containers[0][0]
        wells = containers[1]
        probe_ctr = 1

        for well in wells:
            probe_name = f"id_probe_{probe_ctr}"
            seq_1 = "".join(random.choices("ATCG", k=18))
            seq_2 = "".join(random.choices("ATCG", k=18))

            new_reagent = self.create_instance(
                self.query_template_by_component_v2(
                    "content", "reagent", rg_code, "1.0"
                )[0].euid,
                {
                    "properties": {
                        "probe_name": probe_name,
                        "probe_seq_1": seq_1,
                        "probe_seq_2": seq_2,
                    }
                },
            )
            self.create_generic_instance_lineage_by_euids(well.euid, new_reagent.euid)
            probe_ctr += 1
        
        self.session.commit()
        return plate.euid
    
    def create_reagent(
        self, 
        template_euid: str, 
        properties: Optional[Dict[str, Any]] = None,
        lot_number: Optional[str] = None,
    ):
        """
        Create a reagent from a template.
        
        Args:
            template_euid: Template EUID for the reagent
            properties: Additional properties
            lot_number: Lot number for the reagent
            
        Returns:
            Created reagent object
        """
        json_addl_overrides = {"properties": properties or {}}
        if lot_number:
            json_addl_overrides["properties"]["lot_number"] = lot_number
        return self.create_instance(template_euid, json_addl_overrides)

