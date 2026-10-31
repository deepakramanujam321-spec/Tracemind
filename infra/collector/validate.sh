#!/usr/bin/env sh
# Validate the collector config with the same image compose uses.
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
docker run --rm -v "$DIR/config.yaml:/etc/otelcol/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:0.116.1 validate --config=/etc/otelcol/config.yaml
