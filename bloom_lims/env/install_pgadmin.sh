
# SOURCE ME FROM BASH
# This script is meant to be run from the root of the repo after running: source bloom_activate.sh
# It will install pgadmin4 and create the necessary directories for it to run
# https://www.pgadmin.org/download/pgadmin-4-python/

echo "Installing pgadmin4 to conda BLOOM env.  You will require sudo access to create the install directories for pgadmin. (i think... double check if this is still true)"
sleep 2

# Verify BLOOM environment is active
if [[ "$CONDA_DEFAULT_ENV" != "BLOOM" ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t BLOOM conda environment not active. Run 'source bloom_activate.sh' first.\n"
    sleep 3
    return 1
fi

pipBLOOM=$(dirname $(which python))"/pip"

$pipBLOOM install pgadmin4

if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t problem installing pgadmin4 \n"
    sleep 3
    return 1
fi

echo "\n\n\tNOTE::: For the following commands, you must have sudo access.  Please enter the sudo password when prompted.\n\n"

sudo mkdir -p /var/lib/pgadmin
if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t problem creating /var/lib/pgadmin \n"
    sleep 3
    return 1
fi  
sudo mkdir -p /var/log/pgadmin
if [[ $? -ne 0 ]]; then
    echo "\n\n\n\n\n\tERROR\n\t\t problem creating /var/log/pgadmin \n"
    sleep 3
    return 1
fi

sudo chown $USER /var/lib/pgadmin
sudo chown $USER /var/log/pgadmin

echo "\n\tREADY TO LAUNCH PGADMIN4:  from an active BLOOM conda env, type 'pgadmin4' and if this is a new setup, enter the email and pw you will use to login to pgadmin.\n\n"
echo "\nYou will be prompted for the email and password for the pgadmin admin user to log in to the pgadmin web interface.\n"
echo "\nThe terminal will block after you enter this information, and the server will be available at http://127.0.0.1:5050 \n"

# pgadmin4
