#!/usr/bin/env bash

# Default values
host="0.0.0.0"
port=8911
mode="dev"

unset HTTP_PROXY
unset HTTPS_PROXY

# Parse arguments with nicer flags
while [[ $# -gt 0 ]]; do
  case $1 in
    --host)
      host="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --mode)
      mode="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--host <host>] [--port <port>] [--mode <dev|prod>]"
      echo "  --host     Host to bind (default: 0.0.0.0)"
      echo "  --port     Port to bind (default: 8911)"
      echo "  --mode     Run mode: 'dev' for development, 'prod' for production (default: dev)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help or -h for usage information."
      exit 1
      ;;
  esac
done

# Detect the number of CPU cores
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  num_cores=$(nproc)
elif [[ "$OSTYPE" == "darwin"* ]]; then
  num_cores=$(sysctl -n hw.ncpu)
else
  echo "Unsupported OS type: $OSTYPE"
  exit 1
fi

# Calculate the number of workers (2 * number of cores) - 1
num_workers=$(( (num_cores * 2) - 1 ))


# if selfsigned.crt and selfsigned.key do not exist, create them
if [ ! -f "selfsigned.crt" ] || [ ! -f "selfsigned.key" ]; then
  echo "Creating self-signed SSL certificate..."
  ./bloom_lims/bin/create_ssl.sh
fi


# Run Uvicorn for development or Gunicorn for production
if [[ "$mode" == "dev" ]]; then
  echo "Running in development mode on $host:$port"
  sleep 2
  uvicorn main:app \
    --reload \
    --log-level trace \
    --port $port \
    --timeout-keep-alive 303 \
    --host $host \
    --ssl-certfile /etc/letsencrypt/live/daylilifx.duckdns.org/fullchain.pem \
    --ssl-keyfile /etc/letsencrypt/live/daylilifx.duckdns.org/privkey.pem
elif [[ "$mode" == "prod" ]]; then
  echo "Running in production mode on $host:$port"
  echo "Using $num_workers workers"
  sleep 4
  gunicorn main:app \
    -w $num_workers \
    -k uvicorn.workers.UvicornWorker \
    --log-level trace \
    --timeout 303 \
    --bind $host:$port \
    --ssl-certfile /etc/letsencrypt/live/daylilifx.duckdns.org/fullchain.pem \
    --ssl-keyfile /etc/letsencrypt/live/daylilifx.duckdns.org/privkey.pem
else
  echo "Invalid mode: $mode"
  echo "Use --mode <dev|prod> to specify the run mode."
  exit 1
fi


# sudo apt install certbot
# sudo mkdir -p /var/www/html/.well-known/acme-challenge
# sudo certbot certonly --webroot -w /var/www/html -d daylilyifx.duckdns.org