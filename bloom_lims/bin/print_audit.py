import os
import sys

def get_object_history(euid, session, bloom_core):
    # Function to fetch and format the details of a given object
    def fetch_object_details(orm_instance):
        return {
            "EUID": orm_instance.euid,
            "Created Date": orm_instance.created_dt,
            "Type": orm_instance.type,
            "Subtype": orm_instance.subtype,
            "Version": orm_instance.version,
        }

    # Recursive function to traverse the graph
    def traverse_history(orm_instance):
        history = [fetch_object_details(orm_instance)]

        # Traverse child_of_lineages to find parent instances
        for lineage in orm_instance.child_of_lineages:
            parent_instance = lineage.parent_instance
            if parent_instance:
                history.extend(traverse_history(parent_instance))

        return history

    # Start with the provided EUID
    initial_instance = session.query(bloom_core).filter_by(euid=euid).first()
    if initial_instance:
        return traverse_history(initial_instance)
    else:
        return []


import pytest
from bloom_lims.bdb import BLOOMdb3
from bloom_lims.bdb import BloomWorkflow, BloomWorkflowStep, BloomObj
import sys


bob = BloomWorkflow(BLOOMdb3())

# Usage

report = get_object_history(sys.argv[1], bob.session, bob.Base.classes.generic_instance)

# Printing the report
for item in report:
    print(
        f"EUID: {item['EUID']}, Created: {item['Created Date']}, Type: {item['Type']}, Subtype: {item['Subtype']}, Version: {item['Version']}"
    )
