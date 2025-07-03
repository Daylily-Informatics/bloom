# Source me

# Conda install steps credit: https://gist.github.com/gwangjinkim/f13bf596fefa7db7d31c22efd1627c7a

set -a
source .env
set +a

# set the followiung in your .env file
PGDATA=${PGDATA:-bloom_lims/database/bloom_lims}
PGUSER=${PGUSER:-$USER}
PGPASSWORD=${PGPASSWORD:-SETINDOTENV}
PGDBNAME=${PGDBNAME:-bloom_lims}
PGPORT=${PGPORT:-5445}
# Optional starting value for the file index sequence (FI euid prefix)
FILE_INDEX_START=${FILE_INDEX_START:-1}

echo "FISTART: $FILE_INDEX_START"
sleep 5
source bloom_lims/bin/install_miniconda


if ! command -v conda >/dev/null 2>&1; then
    source /root/miniconda3/etc/profile.d/conda.sh
else
    echo "Miniconda is already installed. Proceeding."
fi


sleep 5
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
sleep 10

export PGPORT=5445
echo "SHELL IS: $SHELL"

# Create database
initdb -D $PGDATA

# start server
pg_ctl -D $PGDATA -o "-p $PGPORT" -l $PGDATA/db.log start 

psql -U $PGUSER -d postgres << EOF

ALTER USER $PGUSER PASSWORD '$PGPASSWORD';

EOF

createdb --owner $PGUSER $PGDBNAME

# create the schema/db from the template

envsubst < bloom_lims/env/postgres_schema_v3.sql | psql -U "$PGUSER" -d "$PGDBNAME" -w
if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t Failed to create database schema. Please check the error message above and try again.\n"
    sleep 3
    return 1
else
    echo "Database schema and tables created successfully."
    echo "You may use the pgsql datastore $PGDATA to connect to the '$PGDBNAME' databse using $PGUSER and pw: $PGPASSWORD and connect to database: $PGDBNAME ."
fi


echo "Setting starting file index to $FILE_INDEX_START"
PGPORT=5445 psql -U "$PGUSER" -d "$PGDBNAME" -c "ALTER SEQUENCE fi_instance_seq RESTART WITH $FILE_INDEX_START;" || {
        echo "Failed to set file index start" && return 1
    }
unset FILE_INDEX_START

echo "\n\n\nSeeding the database templates now...\n\n\n"


# The actions need to be available for some other containers to be seeded, so we do them first
for file in $(ls ./bloom_lims/config/*/*json | grep  'action/' | grep -v 'metadata.json' | sort); do
    echo "$file"
    python scripts/seed_db_containersGeneric.py "$file"
done

# Seed the remaining templates
for file in $(ls ./bloom_lims/config/*/*json | grep -v 'metadata.json'  | grep -v 'action/' | sort); do
    echo "$file"
    python scripts/seed_db_containersGeneric.py "$file"
done

# And create some of the singleton assay objects
python scripts/pregen_AY.py go

echo "\n\n\nBloom Installation Is Complete. Postgres should be running in the background, you can start the bloom ui with 
bash scripts/run_bloomui[_local].sh --port 8911 ' and then navigate to http://localhost:8911 in your browser.\n\n\n"
echo "complete"
 
