# source me

conda activate BLOOM

PGDATA=bloom_lims/database/bloom_lims
PGUSER=$USER
PGPASSWORD=passw0rd
PGDBNAME=bloom

psql  -U $PGUSER -d $PGDBNAME -p 5445

# SET search_path TO bloom;