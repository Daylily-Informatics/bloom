"""
BLOOM LIMS Domain - Content Classes

This module contains content-related classes for samples, reagents,
and other materials.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging
import random
from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


class BloomContent(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_content(self, template_euid):
        """_summary_

        Args:
            template_euid (_type_): _description_

        Returns:
            _type_: _description_
        """

        return self.create_instances(template_euid)



class BloomReagent(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_rgnt_24w_plate_TEST(self, rg_code="idt-probes-rare-mendelian"):
        # I am taking a short cut and not taking time to think about making this generic.

        containers = self.create_instances(
            self.query_template_by_component_v2(
                "container", "plate", "fixed-plate-24", "1.0"
            )[0].euid
        )

        plate = containers[0][0]
        wells = containers[1]
        probe_ctr = 1

        for i in wells:
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
            self.create_generic_instance_lineage_by_euids(i.euid, new_reagent.euid)
            probe_ctr += 1
        self.session.commit()
        return plate.euid




__all__ = [
    "BloomContent",
    "BloomReagent",
]
