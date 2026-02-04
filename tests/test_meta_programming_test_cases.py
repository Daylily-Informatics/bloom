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
            if template.type == "assay":
                pass  # Expected to fail if already instantiated
            else:
                pytest.fail(
                    f"Error creating instances for template: {template.name} ... {template.euid}"
                )


# Attempt database connection; skip entire module if unavailable
try:
    bdb = BLOOMdb3()
    bob = BloomObj(bdb)
    generic_templates = bdb.session.query(bob.Base.classes.generic_template).all()
except Exception as e:
    # Mark module as requiring database, skip during collection if unavailable
    pytestmark = pytest.mark.skip(reason=f"Database unavailable: {e}")
    generic_templates = []

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
