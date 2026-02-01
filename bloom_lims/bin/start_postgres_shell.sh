# source me
# NOTE: Run 'source bloom_activate.sh' first if not already activated

PGDATA=bloom_lims/database/bloom_lims
PGUSER=$USER
PGPASSWORD=passw0rd
PGDBNAME=bloom

psql  -U $PGUSER -d $PGDBNAME -p 5445

# SET search_path TO bloom;