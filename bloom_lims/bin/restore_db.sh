#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "Usage: $0 --sql <file> [--host HOST] [--port PORT] [--user USER] [--password PASSWORD] [--dbname DB]"
  exit 1
}

SQL_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sql)
      SQL_FILE="$2"
      shift 2
      ;;
    --host)
      PGHOST="$2"
      shift 2
      ;;
    --port)
      PGPORT="$2"
      shift 2
      ;;
    --user)
      PGUSER="$2"
      shift 2
      ;;
    --password)
      PGPASSWORD="$2"
      shift 2
      ;;
    --dbname)
      PGDBNAME="$2"
      shift 2
      ;;
    --help|-h)
      usage
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

if [[ -z "$SQL_FILE" ]]; then
  echo "SQL file is required"
  usage
fi

PGHOST=${PGHOST:-localhost}
PGPORT=${PGPORT:-5445}
PGUSER=${PGUSER:-${USER:-bloom}}
PGPASSWORD=${PGPASSWORD:-SETTHISPROPERLY}
PGDBNAME=${PGDBNAME:-bloom_lims}

export PGHOST PGPORT PGUSER PGPASSWORD

# Drop the schema to avoid restore conflicts
dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDBNAME"
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDBNAME"

# Restore from the sql file
psql "$PGDBNAME" -v ON_ERROR_STOP=1 < "$SQL_FILE"
