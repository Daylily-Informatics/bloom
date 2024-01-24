# source me
(source bloom_lims/bin/stop_bloom_db.sh || echo "pgsql not running")  && ( rm -rf bloom_lims/database/* || echo "database files already deleted" ) && source bloom_lims/env/install_postgres.sh skip
