# Source me
#
# This script is for INITIAL SETUP only - it creates the BLOOM conda environment.
# For normal operations, use: source bloom_activate.sh
#
# Conda install steps credit: https://gist.github.com/gwangjinkim/f13bf596fefa7db7d31c22efd1627c7a

PGDATA=${PGDATA:-bloom_lims/database/bloom_lims} 
PGUSER=${PGUSER:-$USER}
PGPASSWORD=${PGPASSWORD:-passw0rd}
export PGDBNAME=${PGDBNAME:-bloom}


# Create a Conda environment named BLOOM if $1 is not set

# github action $1 = ghmac
if [[ "$1" == "" ]]; then
    conda env create -n BLOOM -f bloom_env.yaml
    if [[ $? -ne 0 ]]; then
        echo "\n\n\n\n\n\tERROR\n\t\t Failed to create conda environment. Please check the error message above and try again.\n"
        sleep 3
        return 1
    else
        echo "Conda environment BLOOM created successfully."
    fi
    mkdir -p ~/.config/rclone/ && touch ~/.config/rclone/rclone.conf && cat bloom_lims/env/rclone.conf >> ~/.config/rclone/rclone.conf 
    
    conda activate BLOOM
    if [[ $? -ne 0 ]]; then
        echo "\n\n\n\n\n\tERROR\n\t\t Failed to activate conda environment. Please check the error message above and try again.\n"
        sleep 3
        return 1
    else
        echo "Conda environment BLOOM activated successfully."
    fi
fi

export PGPORT=5445
echo "SHELL IS: $SHELL"

# Create database
initdb -D $PGDATA

# start server
pg_ctl -D $PGDATA -o "-p $PGPORT" -l $PGDATA/db.log start 

PGPORT=5445 psql -U $PGUSER -d postgres << EOF

ALTER USER $PGUSER PASSWORD '$PGPASSWORD';

EOF

# Create the bloom database
createdb --owner $USER $PGDBNAME

# Create bloom role if it doesn't exist (for compatibility with DATABASE_URL using bloom user)
PGPORT=5445 psql -U $PGUSER -d postgres << EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'bloom') THEN
        CREATE ROLE bloom WITH LOGIN PASSWORD 'bloom';
    END IF;
END
\$\$;
GRANT ALL PRIVILEGES ON DATABASE $PGDBNAME TO bloom;
EOF

# create the schema/db from TapDB schema
# TAPDB_SCHEMA_SQL can be set to override the default path to the TapDB schema
TAPDB_SCHEMA_SQL=${TAPDB_SCHEMA_SQL:-../daylily-tapdb/schema/tapdb_schema.sql}

if [[ ! -f "$TAPDB_SCHEMA_SQL" ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t TapDB schema not found at: $TAPDB_SCHEMA_SQL\n\t\t Set TAPDB_SCHEMA_SQL to the correct path.\n"
    sleep 3
    return 1
fi

echo "Applying TapDB schema from: $TAPDB_SCHEMA_SQL"
psql -U "$PGUSER" -d "$PGDBNAME" -w -f "$TAPDB_SCHEMA_SQL"
if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t Failed to apply TapDB schema. Please check the error message above and try again.\n"
    sleep 3
    return 1
else
    echo "TapDB schema applied successfully."
fi

# Grant bloom role permissions on all tables and sequences
echo "Granting permissions to bloom role..."
PGPORT=5445 psql -U $PGUSER -d $PGDBNAME << EOF
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bloom;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bloom;
GRANT USAGE ON SCHEMA public TO bloom;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO bloom;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO bloom;
EOF

# Apply BLOOM-specific prefix sequences for EUID generation
echo "Applying BLOOM prefix sequences..."
psql -U "$PGUSER" -d "$PGDBNAME" -w -f bloom_lims/env/bloom_prefix_sequences.sql
if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t Failed to create BLOOM prefix sequences. Please check the error message above and try again.\n"
    sleep 3
    return 1
else
    echo "BLOOM prefix sequences created successfully."
    echo "You may use the pgsql datastore $PGDATA to connect to the '$PGDBNAME' databse using $PGUSER and pw: $PGPASSWORD and connect to database: $PGDBNAME ."
fi

echo "\n\n\nSeeding the database templates now...\n\n\n"


# The actions need to be available for some other containers to be seeded, so we do them first
for file in $(ls ./bloom_lims/config/*/*json | grep  'action/' | grep -v 'metadata.json' | sort); do
    echo "$file"
    python seed_db_containersGeneric.py "$file"
done

# Seed the remaining templates
for file in $(ls ./bloom_lims/config/*/*json | grep -v 'metadata.json'  | grep -v 'action/' | sort); do
    echo "$file"
    python seed_db_containersGeneric.py "$file"
done

# And create some of the singleton assay objects
python pregen_AY.py go

echo "\n\n\nBloom Installation Is Complete. Postgres should be running in the background, you can start the bloom ui with 
./run_bloomui.sh' and then navigate to http://localhost:8911 in your browser.\n\n\n"
echo "complete"
 
