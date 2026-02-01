
# Create an ubuntu 22.04 AMI instance, using 8-16vCPU and reasonable memory and 60BG disk (this is to get started, 
#  we can always increase later).  I have only tested on x86_64, but arm64 should work too. 
# Launch your instance ** Make sure the ssh port is open in your AWS settings, as well as port 8911 and 8118. http and https, ssh anb dns are good ideas too.

# ssh into the box ssh -i .pem ubuntu@ip
ssh-keygen # defaults


# first, add ~/.ssh/id_rsa.pub to github.
# add some system packages
sudo apt-get update
sudo apt-get install -y htop glances atop emacs tmux git rclone fd-find # this may take 10min & when the ncurses menu pops up, i just acepted defaults.


# Create place to clone repos
mkdir -p ~/projects/git && cd ~/projects/git

# Clone bloom & move into it
git clone git@github.com:Daylily-Informatics/bloom.git
cd bloom


 ##
#  Add Some Config Files ( see each repo for details on what goes in them)
 ##

# ~/.aws/{config,credentials}
# and
#  ~/.config/fedex/fedex_prod.yaml

 ##
#  From here we follow the README installation section.
 ##

# Install CONDA for the user
cd ~
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh #accept all defaults


# The last option gave permission to modify your .bashrc so conda is available on your future new shells.  The shell you are in does not have conda active.
# logout and logback in

###
exit
# Then ssh  BACK TO THE BOX AGAIN
###

# You now should see a '(base)' to the left of your prompt.  This means conda is active.  If you don't see it, you can activate it with `conda activate base`   

cd ~/projects/git/bloom/


 ##
#  Configuration (see the cognito.md doc for details)
 ##

# Copy the config template to your user config directory:
#   mkdir -p ~/.config/bloom
#   cp config/bloom-config-template.yaml ~/.config/bloom/bloom-config.yaml
#
# Edit ~/.config/bloom/bloom-config.yaml to set:
#   - Cognito settings (auth.cognito_*)
#   - S3 bucket prefix (storage.s3_prefix)
#   - Database settings if needed
#
# See bloom_lims/docs/cognito.md for detailed configuration instructions.


# Install the BLOOM conda environment
# The script also installs postgres and creates the database, and spins it up so if you get no error, it will now be running on a non-std port...need to look
# When the server restarts, postgres will be down, and you can restart it with source "bloom_lims_bin/start_postgres.sh"
source bloom_lims/env/install_postgres.sh # this can take a few min to 10+min, it depends on the hardware.

# Test your install
pytest  # You should get mostly successes, and some warnings (which are fine)


# The DB is running, we can now start the UI
# Open a tmux session which can be detached and reattached to later.
tmux new -s bloom
source bloom_activate.sh
bloom gui  # or: source run_bloomui.sh (edit gunicorn command for external IP)
# ctrl-b d to detach from the tmux session
# this will run, logging to stdout.  

# And that should return something like
TERM_OUT="""
(BLOOM) ubuntu@ip-172-31-7-22:~/projects/git/bloom$ source run_bloomui.sh
INFO:     Will watch for changes in these directories: ['/home/ubuntu/projects/git/bloom']
INFO:     Uvicorn running on http://127.0.0.1:8911 (Press CTRL+C to quit)
INFO:     Started reloader process [6128] using StatReload
INFO:     Started server process [6130]
INFO:     Waiting for application startup.
TRACE:    ASGI [1] Started scope={'type': 'lifespan', 'asgi': {'version': '3.0', 'spec_version': '2.0'}, 'state': {}}
TRACE:    ASGI [1] Receive {'type': 'lifespan.startup'}
TRACE:    ASGI [1] Send {'type': 'lifespan.startup.complete'}
INFO:     Application startup complete.
"""
# the shell is blocked while the service runs.
# This can be made a service and directed to log to a file if you wish.


# Next, visit the UI at http://ip:8911/ and you should be able to auth with an rcrf.org email.
# Dewey is the file manager app.

echo "fin!"
