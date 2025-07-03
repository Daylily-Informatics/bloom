import json
from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj
import sys
import os


def create_template_from_json(json_file, db):
    """
    Parse the JSON file and create new *_template records in the database.

    :param json_file: Path to the JSON file.
    :param db: Instance of BLOOMdb3 for database interactions.
    """
    btype = os.path.splitext(os.path.basename(json_file))[0]

    table_prefix = os.path.dirname(json_file).split("/")[-1]

    euid_prefix = os.path.dirname(json_file) + "/metadata.json"
    md_json = json.load(open(euid_prefix))

    with open(json_file, "r") as file:
        data = json.load(file)

    for b_sub_type, versions in data.items():
        for version, details in versions.items():
            # Prepare json_addl field
            json_addl = details  # json.dumps(details)

            obj_prefix = (
                md_json["euid_prefixes"]["default"]
                if btype not in md_json["euid_prefixes"]
                else md_json["euid_prefixes"][btype]
            )

            try:
                prefix_in_schema = (
                    os.popen(
                        f"""grep -s "\'{obj_prefix}\' THEN" bloom_lims/env/postgres_schema_v3.sql | wc -l"""
                    )
                    .readline()
                    .rstrip()
                    .lstrip()
                )
                if prefix_in_schema != "1":
                    raise Excetpion(
                        f"Prefix {obj_prefix} not found in schema. Please add it to the schema first.  You should probably clear the database if this was a first seeding attempt"
                    )
            except Exception as e:
                print(f"Error in {json_file}\n\n", e)
                sys.exit(1)
            print("xxx", table_prefix)
            # Create new table_template record
            table_template = db.Base.classes.generic_template
            new_table_template = table_template(
                name=f"{btype}:{b_sub_type}:{version}",
                super_type=table_prefix,
                btype=btype,
                b_sub_type=b_sub_type,
                version=version,
                json_addl=json_addl,
                instance_prefix=obj_prefix,
                is_singleton=True,
                bstatus="ready",
                polymorphic_discriminator=f"{table_prefix}_template",
            )

            db.session.add(new_table_template)
            db.session.commit()


def main():
    db = BLOOMdb3(app_username="bloom_db_init")
    # Path to the JSON file
    json_file_path = sys.argv[1]

    # Process the JSON and create records
    create_template_from_json(json_file_path, db)

    # Close the database connection
    db.close()


if __name__ == "__main__":
    main()
