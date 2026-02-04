import json
from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj
import sys
import os
from sqlalchemy import text


def ensure_sequence_exists(db, prefix: str) -> None:
    """
    Ensure the EUID sequence exists for a given prefix.

    The set_generic_instance_euid() trigger requires a sequence named
    {lowercase_prefix}_instance_seq for each template prefix. This function
    creates the sequence if it doesn't exist, making the seeding process
    resilient to new prefixes being added to metadata.json files.

    Args:
        db: BLOOMdb3 database instance
        prefix: The instance_prefix (e.g., 'DAT', 'LM', 'HEV')
    """
    seq_name = f"{prefix.lower()}_instance_seq"

    # Check if sequence exists
    result = db.session.execute(text("""
        SELECT 1 FROM information_schema.sequences
        WHERE sequence_schema = 'public' AND sequence_name = :seq_name
    """), {"seq_name": seq_name})

    if result.fetchone() is None:
        # Create the sequence
        db.session.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"))
        db.session.execute(text(
            f"COMMENT ON SEQUENCE {seq_name} IS 'Auto-created EUID sequence for prefix {prefix}'"
        ))
        db.session.commit()
        print(f"  ✓ Created missing sequence: {seq_name}")


def create_template_from_json(json_file, db):
    """
    Parse the JSON file and create new *_template records in the database.

    :param json_file: Path to the JSON file.
    :param db: Instance of BLOOMdb3 for database interactions.
    """
    type_name = os.path.splitext(os.path.basename(json_file))[0]

    table_prefix = os.path.dirname(json_file).split("/")[-1]

    euid_prefix = os.path.dirname(json_file) + "/metadata.json"
    md_json = json.load(open(euid_prefix))

    with open(json_file, "r") as file:
        data = json.load(file)

    for subtype, versions in data.items():
        for version, details in versions.items():
            # Prepare json_addl field
            json_addl = details  # json.dumps(details)

            obj_prefix = (
                md_json["euid_prefixes"]["default"]
                if type_name not in md_json["euid_prefixes"]
                else md_json["euid_prefixes"][type_name]
            )

            # Ensure the EUID sequence exists for this prefix
            # This auto-creates sequences for new prefixes added to metadata.json
            ensure_sequence_exists(db, obj_prefix)

            # TapDB uses sequence-based EUID generation via bloom_prefix_sequences.sql
            # No need to check for CASE expressions in legacy schema
            print(f"Seeding {table_prefix} with prefix {obj_prefix}")
            # Create new table_template record
            table_template = db.Base.classes.generic_template
            new_table_template = table_template(
                name=f"{type_name}:{subtype}:{version}",
                category=table_prefix,
                type=type_name,
                subtype=subtype,
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
