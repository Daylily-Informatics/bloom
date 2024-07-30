import json
from bloom_lims.db import BLOOMdb3

from bloom_lims.bobjs import BloomObj
from bloom_lims.bobjs import (
    BloomContainer,
    BloomContainerPlate,
    BloomContent,
    BloomWorkflow,
    BloomWorkflowStep,
    BloomEquipment,
)


###
#
# This test DOES reflect appropriate initial use of the polymorphic ORM version now replacing earlier versions.
#
###


def _check_create_instances_ret_matrix(bobj_matrix, expected_lens=[None, None]):
    """
    Check that the template creation function returns the correct number of objects
    One checking one level of nesting
    """
    ret_check = False
    if len(bobj_matrix[0]) == expected_lens[0]:
        ret_check = True
    else:
        ret_check = False
    if len(bobj_matrix[1]) == expected_lens[1] and ret_check:
        ret_check = True
    else:
        ret_check = False

    return ret_check


def test_intantiating_bloom_objects():
    bdb = BLOOMdb3()

    cr = BloomContainer(bdb)
    assert cr.__class__.__name__ == "BloomContainer"

    crp = BloomContainerPlate(bdb)
    assert crp.__class__.__name__ == "BloomContainerPlate"

    ct = BloomContent(bdb)
    assert ct.__class__.__name__ == "BloomContent"

    wf = BloomWorkflow(bdb)
    assert wf.__class__.__name__ == "BloomWorkflow"

    ws = BloomWorkflowStep(bdb)
    assert ws.__class__.__name__ == "BloomWorkflowStep"

    eq = BloomEquipment(bdb)
    assert eq.__class__.__name__ == "BloomEquipment"


def test_create_instances_from_instance_templates():
    bdb = BLOOMdb3()
    bob = BloomObj(bdb)
    generic_templates = bdb.session.query(bob.Base.classes.generic_template).all()
    err = False
    for template in generic_templates:
        try:
            bob.create_instances(template.euid)
        except Exception as e:
            if template.btype == "assay":
                pass  # Expected to fail if already instantiated
            else:
                err = True
                raise Exception(
                    f"Error creating instances for template: {template.name} ... {template.euid}"
                )

    if err:
        raise Exception(
            "Error creating instances for template: {}".format(template.euid)
        )
    else:
        assert 1 == 1
