import pytest
from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj
import sys


class BaseTest:
    def setup_method(self, method):
        # Setup code here
        pass

    def check_instance_creation(self, template, bob):
        try:
            bob.create_instances(template.euid)
        except Exception as e:
            if template.btype == "assay":
                pass  # Expected to fail if already instantiated
            else:
                pytest.fail(
                    f"Error creating instances for template: {template.name} ... {template.euid}"
                )


bdb = BLOOMdb3()
bob = BloomObj(bdb)
generic_templates = bdb.session.query(bob.Base.classes.generic_template).all()

for template in generic_templates:
    # Dynamically create a test class for each template
    class_name = (
        f"TestEuid{template.euid.replace('-', '')}"  # Ensure valid Python class names
    )
    class_body = {
        "test_instance_creation": lambda self: BaseTest.check_instance_creation(
            self, template, bob
        )
    }
    new_test_class = type(class_name, (BaseTest,), class_body)

    # Add the new test class to the current module for pytest to find
    setattr(sys.modules[__name__], class_name, new_test_class)
