#!/usr/bin/env python3
"""Find action by name pattern in workflow hierarchy."""
import sys
import json
sys.path.insert(0, '.')

from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj

bobdb = BloomObj(BLOOMdb3(app_username='test@test.com'))
obj = bobdb.get_by_euid('AY1')

found_actions = []

def find_action(obj, action_name_pattern, depth=0):
    if obj.json_addl and 'action_groups' in obj.json_addl:
        for gk, gv in obj.json_addl['action_groups'].items():
            for ak, av in gv.get('actions', {}).items():
                if action_name_pattern.lower() in av.get('action_name', '').lower():
                    found_actions.append({
                        'euid': obj.euid,
                        'action_key': ak,
                        'action_name': av.get('action_name'),
                        'captured_data': av.get('captured_data', {})
                    })

    if depth < 4 and hasattr(obj, 'parent_of_lineages'):
        for lin in obj.parent_of_lineages[:30]:
            child = lin.child_instance
            if child and not child.is_deleted:
                find_action(child, action_name_pattern, depth+1)

# Search for Register Specimen action
find_action(obj, 'Register')
for a in found_actions:
    print(f"EUID: {a['euid']}")
    print(f"Action: {a['action_name']}")
    print(f"Key: {a['action_key']}")
    print(f"captured_data: {json.dumps(a['captured_data'], indent=2)}")
    print("---")

