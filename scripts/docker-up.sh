#!/bin/sh
# Build and start the containerised API (reusing a Postgres already on the host if GOIP_DOCKER_DB_URL is set).
set -e
cd "$(dirname "$0")/.."
mkdir -p certs
[ -e certs/corp-ca.pem ] || : > certs/corp-ca.pem   # an empty file means "no corporate certificate"
if [ -n "$GOIP_DOCKER_DB_URL" ]; then
  # Reusing a Postgres that already runs on the host: do not start a second one.
  exec docker compose --profile container up --build -d --no-deps api
fi
exec docker compose --profile container up --build -d api
