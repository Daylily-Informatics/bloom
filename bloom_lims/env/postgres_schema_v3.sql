-- Create a new schema
CREATE SCHEMA $PGDBNAME;

-- seems to already exist on MAC pgsql, not on ubuntu?
CREATE EXTENSION IF NOT EXISTS pgcrypto;

/*
  ==> Run this in all client code before updates or delete statements :: SET session.current_username = 'application_username';

      This is how the user responsible for the edit/delete is recorded.  If this is not set, a default user is used.
      .... and no data should be actually deleted, only the del flag set. Delete operations are intercepted

      NOTE ... you might need to install the postgres extension: pgcrypto (https://www.postgresql.org/docs/9.0/pgcrypto.html)
*/


/*
Soft Delete Function
*/

CREATE OR REPLACE FUNCTION soft_delete_row()
RETURNS TRIGGER AS $$
DECLARE
    jsonData JSON;
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;
    -- Check if the 'is_deleted' column exists in the table
    IF EXISTS(SELECT 1 FROM information_schema.columns 
              WHERE table_name = TG_TABLE_NAME 
              AND column_name = 'is_deleted') THEN
        -- Set 'is_deleted' to TRUE for the row identified by UUID
        EXECUTE format('UPDATE %I SET is_deleted = TRUE WHERE uuid = $1', TG_TABLE_NAME) USING OLD.uuid;

        jsonData := row_to_json(OLD); -- Convert the OLD record to JSON

        INSERT INTO audit_log (rel_table_name, rel_table_uuid_fk, rel_table_euid_fk, changed_by, operation_type, deleted_record_json)
        VALUES (TG_TABLE_NAME, OLD.uuid, OLD.euid, app_username, 'DELETE', jsonData);
    
        RETURN NULL; -- Cancel the delete operation
    ELSE
        -- If 'is_deleted' column doesn't exist, continue with the delete
        RETURN OLD;
    END IF;
END;
$$ LANGUAGE plpgsql;
commit;

/*
......
*/
CREATE SEQUENCE generic_template_seq;
CREATE TABLE generic_template (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE NOT NULL DEFAULT ('GT' || nextval('generic_template_seq')),
    name TEXT NOT NULL,
    instance_prefix TEXT NOT NULL,
    polymorphic_discriminator TEXT NOT NULL,
    super_type TEXT NOT NULL,
    btype TEXT NOT NULL, -- Base type of test requisition
    b_sub_type TEXT NOT NULL, -- Sub-type of test requisition
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version TEXT NOT NULL,
    json_addl JSONB NOT NULL, -- To store additional properties
    json_addl_schema JSONB, -- To store additional properties schema
    bstatus TEXT NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_singleton BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE UNIQUE INDEX idx_genric_template_unique_singleton_key 
ON generic_template (super_type, btype, b_sub_type, version) 
WHERE is_singleton = TRUE;

CREATE INDEX idx_generic_template_singleton ON generic_template(is_singleton);
CREATE INDEX idx_generic_template_type ON generic_template(btype);
CREATE INDEX idx_generic_template_euid ON generic_template(euid);
CREATE INDEX idx_generic_template_is_deleted ON generic_template(is_deleted);
CREATE INDEX idx_generic_template_super_type ON generic_template(super_type);
CREATE INDEX idx_generic_template_b_sub_type ON generic_template(b_sub_type);
CREATE INDEX idx_generic_template_version ON generic_template(version);
CREATE INDEX idx_generic_template_mod_df ON generic_template(modified_dt);
CREATE INDEX idx_generic_template_instance_prefix ON generic_template(instance_prefix);
CREATE INDEX idx_generic_template_polymorphic_discriminator  ON generic_template(polymorphic_discriminator);
CREATE INDEX idx_generic_template_json_addl_gin ON generic_template USING GIN (json_addl);
CREATE INDEX idx_generic_template_composite 
ON generic_template(super_type, btype, b_sub_type, version, is_deleted);

ALTER TABLE generic_template
ADD CONSTRAINT unique_super_type_btype_b_sub_type_version
UNIQUE (super_type, btype, b_sub_type, version);

CREATE OR REPLACE TRIGGER trigger_generic_template_soft_delete
BEFORE DELETE ON generic_template
FOR EACH ROW EXECUTE FUNCTION soft_delete_row();

CREATE SEQUENCE generic_instance_seq;
CREATE SEQUENCE cx_instance_seq;
CREATE SEQUENCE mx_instance_seq;
CREATE SEQUENCE dx_instance_seq;
CREATE SEQUENCE ax_instance_seq;
CREATE SEQUENCE wx_instance_seq;
CREATE SEQUENCE wsx_instance_seq;
CREATE SEQUENCE trx_instance_seq;
CREATE SEQUENCE ex_instance_seq;
CREATE SEQUENCE gx_instance_seq;
CREATE SEQUENCE cwx_instance_seq;
CREATE SEQUENCE ay_instance_seq;
CREATE SEQUENCE xx_instance_seq;
CREATE SEQUENCE wsq_instance_seq;
CREATE SEQUENCE mrxq_instance_seq;
CREATE SEQUENCE mcxq_instance_seq;
CREATE SEQUENCE fx_instance_seq;
CREATE SEQUENCE fi_instance_seq;
CREATE SEQUENCE fs_instance_seq;
CREATE SEQUENCE ev_instance_seq;

CREATE TABLE generic_instance (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE,
    name TEXT NOT NULL,
    json_addl JSONB NOT NULL, -- To store additional properties
    btype TEXT NOT NULL,
    polymorphic_discriminator TEXT NOT NULL,
    super_type TEXT NOT NULL,
    b_sub_type TEXT NOT NULL,
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version TEXT NOT NULL,
    bstatus TEXT NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    template_uuid UUID NOT NULL REFERENCES generic_template(uuid),
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX idx_genric_instance_unique_singleton_key 
ON generic_instance (super_type, btype, b_sub_type, version) 
WHERE is_singleton = TRUE;

CREATE INDEX idx_generic_instance_polymorphic_discriminator ON generic_instance(polymorphic_discriminator);
CREATE INDEX idx_generic_instance_type ON generic_instance(btype);
CREATE INDEX idx_generic_instance_euid ON generic_instance(euid);
CREATE INDEX idx_generic_instance_is_deleted ON generic_instance(is_deleted);
CREATE INDEX idx_generic_instance_template_uuid ON generic_instance(template_uuid);
CREATE INDEX idx_generic_instance_super_type ON generic_instance(super_type);
CREATE INDEX idx_generic_instance_b_sub_type ON generic_instance(b_sub_type);
CREATE INDEX idx_generic_instance_version ON generic_instance(version);
CREATE INDEX idx_generic_instance_mod_df ON generic_instance(modified_dt);
CREATE INDEX idx_generic_instance_json_addl_gin ON generic_instance USING GIN (json_addl);
CREATE INDEX idx_generic_instance_singleton ON generic_instance(is_singleton);
CREATE INDEX idx_generic_instance_composite 
ON generic_template(super_type, btype, b_sub_type, version, is_deleted);

CREATE OR REPLACE TRIGGER trigger_generic_instance_soft_delete
BEFORE DELETE ON generic_instance
FOR EACH ROW EXECUTE FUNCTION soft_delete_row();

CREATE OR REPLACE FUNCTION set_generic_instance_euid()
RETURNS TRIGGER AS $$
DECLARE
    prefix TEXT;
    sequence_name TEXT;
BEGIN
    -- Fetch the instance_prefix from generic_template
    SELECT instance_prefix INTO prefix FROM generic_template WHERE uuid = NEW.template_uuid;
    -- Set the euid of the new generic_instance
    sequence_name := CASE
            WHEN prefix = 'CX' THEN nextval('cx_instance_seq')
            WHEN prefix = 'MX' THEN nextval('mx_instance_seq')
            WHEN prefix = 'DX' THEN nextval('dx_instance_seq')
            WHEN prefix = 'AX' THEN nextval('ax_instance_seq')
            WHEN prefix = 'WX' THEN nextval('wx_instance_seq')
            WHEN prefix = 'WSX' THEN nextval('wsx_instance_seq')
            WHEN prefix = 'TRX' THEN nextval('trx_instance_seq')
            WHEN prefix = 'EX' THEN nextval('ex_instance_seq')
            WHEN prefix = 'GX' THEN nextval('gx_instance_seq')
            WHEN prefix = 'CWX' THEN nextval('cwx_instance_seq')
            WHEN prefix = 'AY' THEN nextval('ay_instance_seq')
            WHEN prefix = 'XX' THEN nextval('xx_instance_seq')
            WHEN prefix = 'QX' THEN nextval('wsq_instance_seq')
            WHEN prefix = 'MRX' THEN nextval('mrxq_instance_seq')
            WHEN prefix = 'MCX' THEN nextval('mcxq_instance_seq')
            WHEN prefix = 'FX' THEN nextval('fx_instance_seq')
            WHEN prefix = 'FI' THEN nextval('fi_instance_seq')
            WHEN prefix = 'FS' THEN nextval('fs_instance_seq')
            WHEN prefix = 'EV' THEN nextval('ev_instance_seq')

            -- Add more cases for other prefixes
            ELSE nextval('generic_instance_seq') -- Default sequence
        END;

    NEW.euid := prefix || sequence_name;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_set_generic_instance_euid
BEFORE INSERT ON generic_instance
FOR EACH ROW EXECUTE FUNCTION set_generic_instance_euid();




CREATE SEQUENCE generic_instance_lineage_seq;
CREATE TABLE generic_instance_lineage (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    euid TEXT UNIQUE NOT NULL DEFAULT ('GL' || nextval('generic_instance_lineage_seq')),
    parent_instance_uuid UUID NOT NULL REFERENCES generic_instance(uuid),
    parent_type TEXT NOT NULL,
    child_type TEXT NOT NULL, 
    polymorphic_discriminator TEXT NOT NULL,
    child_instance_uuid UUID NOT NULL REFERENCES generic_instance(uuid),
    created_dt TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name TEXT NOT NULL,
    super_type TEXT NOT NULL,
    btype TEXT,
    b_sub_type TEXT,
    json_addl JSONB,
    bstatus TEXT,    
    version TEXT,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    modified_dt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE,
    relationship_type TEXT
);

CREATE INDEX idx_generic_instance_lineage_euid ON generic_instance_lineage(euid);
CREATE INDEX idx_generic_instance_lineage_is_deleted ON generic_instance_lineage(is_deleted);
CREATE INDEX idx_generic_instance_lineage_parent_uuid ON generic_instance_lineage(parent_instance_uuid);
CREATE INDEX idx_generic_instance_lineage_child_uuid ON generic_instance_lineage(child_instance_uuid);
CREATE INDEX idx_generic_instance_lineage_mod_dt ON generic_instance_lineage(modified_dt);
CREATE INDEX idx_generic_instance_lineage_polymorphic_discriminator ON generic_instance_lineage(polymorphic_discriminator);
CREATE INDEX idx_generic_instance_lineage_json_addl_gin ON generic_instance_lineage USING GIN (json_addl);
CREATE INDEX idx_generic_instance_lineage_relationship_type ON generic_instance_lineage(relationship_type);

CREATE OR REPLACE TRIGGER generic_instance_lineage_soft_delete
BEFORE DELETE ON generic_instance_lineage
FOR EACH ROW EXECUTE FUNCTION soft_delete_row();


/*
Audit Log Mechanism (could be changed to log changes for each table to a distincy audit log table)
*/
CREATE SEQUENCE audit_log_seq;
CREATE TABLE audit_log (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rel_table_name TEXT NOT NULL,
    column_name TEXT,
    rel_table_uuid_fk UUID NOT NULL,
    rel_table_euid_fk TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT,
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operation_type TEXT CHECK (operation_type IN ('INSERT', 'UPDATE', 'DELETE')),
    json_addl JSONB,
    super_type TEXT,
    deleted_record_json JSONB,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_singleton BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_audit_log_rel_table_name ON audit_log(rel_table_name);
CREATE INDEX idx_audit_log_rel_table_uuid_fk ON audit_log(rel_table_uuid_fk);
CREATE INDEX idx_audit_log_rel_table_euid_fk ON audit_log(rel_table_euid_fk);
CREATE INDEX idx_audit_log_is_deleted ON audit_log(is_deleted);
CREATE INDEX idx_audit_log_operation_type ON audit_log(operation_type);
CREATE INDEX idx_audit_log_changed_at ON audit_log(changed_at);
CREATE INDEX idx_audit_log_changed_by ON audit_log(changed_by);
CREATE INDEX idx_audit_log_json_addl_gin ON audit_log USING GIN (json_addl);


/*
Audit Trigger Mechanisms
*/
CREATE OR REPLACE FUNCTION record_update()
RETURNS TRIGGER AS $$
DECLARE
    r RECORD;
    column_name TEXT;
    old_value TEXT;
    new_value TEXT;
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;

    FOR r IN SELECT * FROM json_each_text(row_to_json(NEW)) LOOP
        column_name := r.key;
        new_value := r.value;
        EXECUTE format('SELECT ($1).%I', column_name) USING OLD INTO old_value;

        IF old_value IS DISTINCT FROM new_value THEN
            INSERT INTO audit_log (rel_table_name, column_name, old_value, new_value, changed_by, rel_table_uuid_fk, rel_table_euid_fk, operation_type)
            VALUES (TG_TABLE_NAME, column_name, old_value, new_value, app_username, NEW.uuid, NEW.euid, TG_OP);
        END IF;
    END LOOP;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION record_delete()
RETURNS TRIGGER AS $$
DECLARE
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;
    
    INSERT INTO audit_log (rel_table_name, rel_table_uuid_fk, rel_table_euid_fk, changed_by, operation_type)
    VALUES (TG_TABLE_NAME, OLD.uuid, OLD.euid, app_username, 'DELETE');
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


-- Function to create the audit triggers for all tables specified in the tables array
CREATE OR REPLACE FUNCTION create_audit_triggers_for_tables(tables TEXT[])
RETURNS void AS $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY tables LOOP
        -- Construct the CREATE TRIGGER statement for UPDATE
        EXECUTE format(
            'CREATE TRIGGER %I_audit_trigger_after_update AFTER UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION record_update();',
            table_name, table_name
        );

        -- Construct the CREATE TRIGGER statement for DELETE
        EXECUTE format(
            'CREATE TRIGGER %I_audit_trigger_after_delete AFTER DELETE ON %I FOR EACH ROW EXECUTE FUNCTION record_delete();',
            table_name, table_name
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;


-- Add all tables which need audit triggers here
SELECT create_audit_triggers_for_tables(ARRAY['generic_template','generic_instance','generic_instance_lineage']);


-- Function to record inserts
CREATE OR REPLACE FUNCTION record_insert()
RETURNS TRIGGER AS $$
DECLARE
    app_username TEXT;
BEGIN
    BEGIN
        app_username := current_setting('session.current_username', true);
    EXCEPTION WHEN OTHERS THEN
        app_username := current_user;
    END;

    -- Insert record into audit_log
    INSERT INTO audit_log (rel_table_name, rel_table_uuid_fk, rel_table_euid_fk, changed_by, operation_type)
    VALUES (TG_TABLE_NAME, NEW.uuid, NEW.euid, app_username, 'INSERT');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to create the insert audit trigger for specified tables
CREATE OR REPLACE FUNCTION create_insert_audit_triggers_for_tables(tables TEXT[])
RETURNS void AS $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY tables LOOP
        -- Construct the CREATE TRIGGER statement for INSERT
        EXECUTE format(
            'CREATE TRIGGER %I_audit_trigger_after_insert AFTER INSERT ON %I FOR EACH ROW EXECUTE FUNCTION record_insert();',
            table_name, table_name
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Add all tables which need insert audit triggers here
SELECT create_insert_audit_triggers_for_tables(ARRAY['generic_template', 'generic_instance', 'generic_instance_lineage']);


/*
Add modification date tracking
*/
CREATE OR REPLACE FUNCTION update_modified_dt()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_dt = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_generic_instance_mod_dt
BEFORE UPDATE ON generic_instance
FOR EACH ROW EXECUTE FUNCTION update_modified_dt();

CREATE TRIGGER update_generic_instance_lineage_mod_dt
BEFORE UPDATE ON generic_instance_lineage
FOR EACH ROW EXECUTE FUNCTION update_modified_dt();

CREATE TRIGGER update_generic_template_mod_dt
BEFORE UPDATE ON generic_template
FOR EACH ROW EXECUTE FUNCTION update_modified_dt();

-- FIN
