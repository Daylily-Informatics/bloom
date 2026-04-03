source ./activate --deploy-name jemx5 --region us-west-2

dayhoff deploy resume \
  --deploy-name jemx5 \
  --deploy-target local \
  --region us-west-2 \
  --service bloom

source /Users/jmajor/.codex/worktrees/c1d6/dayhoff/.dayhoff/local/jemx5/repos/bloom/activate jemx5

bloom db init --force

source /Users/jmajor/.codex/worktrees/c1d6/dayhoff/.dayhoff/local/jemx5/repos/bloom/activate jemx5

bloom server start \
  --port 8912 \
  --background \
  --ssl \
  --cert /Users/jmajor/.local/state/dayhoff/jemx5/certs/cert.pem \
  --key /Users/jmajor/.local/state/dayhoff/jemx5/certs/key.pem

/Users/jmajor/miniconda3/envs/BLOOM-jemx5/bin/python \
  -m uvicorn \
  main:app \
  --host 0.0.0.0 \
  --port 8912 \
  --ssl-keyfile /Users/jmajor/.local/state/dayhoff/jemx5/certs/key.pem \
  --ssl-certfile /Users/jmajor/.local/state/dayhoff/jemx5/certs/cert.pem
