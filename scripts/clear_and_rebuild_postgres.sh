# SOURCE THIS SCRIPT WITH THE BLOOM CONDA ENV ACTIVE

echo "\n\nDo you really wish to stop postgres and irrevocably delete what is there, then replace it with freshly seeded templates, and that is it?"
echo "Type 'yes' to proceed, anything else exits."
read -r response

if [[ "$response" != "yes" ]]; then
  echo "Exiting..."
  exit 1
fi

echo "\n\n___STOPPING POSTGRES___\n\n"
sleep 1
source bloom_lims/bin/stop_bloom_db.sh 

echo "\n\n___REMOVING DATABASE DIRS & FILES___\n\n"
setopt rmstarsilent
rm -rf bloom_lims/database/*
unsetopt rmstarsilent
sleep 1

echo "\n\n___BUILDING POSTGRES && SEEDING WITH TEMPLATES___\n\n"
sleep 1
source bloom_lims/env/install_postgres.sh skip

echo "\n\n___RUNNING TESTS___\n\n"
sleep 1
pytest 