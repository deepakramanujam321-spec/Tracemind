#!/bin/sh
# Applies demo/db/schema.sql to database "app". Usage: init-app.sh <APP_DATABASE_URL>
set -e
psql "$1" -v ON_ERROR_STOP=1 -f "$(dirname "$0")/schema.sql"
