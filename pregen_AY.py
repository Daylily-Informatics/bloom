import json
from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj
import sys
import os
from sqlalchemy.orm.attributes import flag_modified

if sys.argv[1] != "go":
    raise ("this is only for initial seeding of the database")

bob = BloomObj(BLOOMdb3(app_username="bloom_db_init"))


for tobe_locked_assay in (
    bob.session.query(bob.Base.classes.generic_template)
    .filter(bob.Base.classes.generic_template.super_type == "workflow")
    .filter(bob.Base.classes.generic_template.btype == "assay")
    .all()
):
    print(f"WHATISTHIS::: {tobe_locked_assay}")
    gi = bob.create_instances(tobe_locked_assay.euid)[0][0]
    gi.is_singleton = True
    flag_modified(gi, "is_singleton")
    bob.session.commit()
