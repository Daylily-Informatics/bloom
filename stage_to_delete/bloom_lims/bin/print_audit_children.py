def get_children_history(euid, session, bloom_core):
    # Function to fetch and format the details of a given object
    def fetch_object_details(orm_instance):
        return {
            "EUID": orm_instance.euid,
            "Created Date": orm_instance.created_dt,
            "Type": orm_instance.type,
            "Subtype": orm_instance.subtype,
            "Version": orm_instance.version,
        }

    # Recursive function to traverse the graph for child instances
    def traverse_children(orm_instance):
        history = [fetch_object_details(orm_instance)]

        # Traverse parent_of_lineages to find child instances
        for lineage in orm_instance.parent_of_lineages:
            child_instance = lineage.child_instance
            if child_instance:
                history.extend(traverse_children(child_instance))

        return history

    # Start with the provided EUID
    initial_instance = session.query(bloom_core).filter_by(euid=euid).first()
    if initial_instance:
        return traverse_children(initial_instance)
    else:
        return []


import pytest
from bloom_lims.bdb import BLOOMdb3
from bloom_lims.bdb import BloomWorkflow, BloomWorkflowStep, BloomObj
import sys


bob = BloomWorkflow(BLOOMdb3())
bob_wfs = BloomWorkflowStep(BLOOMdb3())


# Usage Example
# Replace 'CX5', session, and bloom_core with your actual data and class
report = get_children_history("CX5", bob.session, bob.Base.classes.generic_instance)

# Printing the report
for item in report:
    print(
        f"EUID: {item['EUID']}, Created: {item['Created Date']}, Type: {item['Type']}, Subtype: {item['Subtype']}, Version: {item['Version']}"
    )
