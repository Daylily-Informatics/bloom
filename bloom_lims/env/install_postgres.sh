# Source me

# Conda install steps credit: https://gist.github.com/gwangjinkim/f13bf596fefa7db7d31c22efd1627c7a

PGDATA=${PGDATA:-bloom_lims/database/bloom_lims} 
PGUSER=${PGUSER:-$USER}
PGPASSWORD=${PGPASSWORD:-passw0rd}
export PGDBNAME=${PGDBNAME:-bloom}


# Create a Conda environment named BLOOM if $1 is not set

# github action $1 = ghmac
if [[ "$1" == "" ]]; then
    #conda create -n BLOOM -y -c conda-forge postgresql python pip ipython pytest psycopg2 sqlalchemy pytz networkx matplotlib cherrypy parallel jinja2   jq && conda activate BLOOM && pip install zebra_day==0.3.0.4 fedex_tracking_day==0.2.6
    conda env create -f bloom_env.yaml
    if [[ $? -ne 0 ]]; then
        echo "\n\n\n\n\n\tERROR\n\t\t Failed to create conda environment. Please check the error message above and try again.\n"
        sleep 3
        return 1
    else
        echo "Conda environment BLOOM created successfully."
    fi
    
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

conda info
# Create database
initdb -D $PGDATA

# start server
pg_ctl -D $PGDATA -o "-p $PGPORT" -l $PGDATA/db.log start 

PGPORT=5445 psql -U $PGUSER -d postgres << EOF

ALTER USER $PGUSER PASSWORD '$PGPASSWORD';

EOF

createdb --owner $USER $PGDBNAME

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

echo "\n\n\nBloom Installation Is Complete. Postgres should be running in the background, you can start the bloom ui with 'python bloomuiiu.py' and then navigate to http://localhost:8080 in your browser.\n\n\n"

return 0

