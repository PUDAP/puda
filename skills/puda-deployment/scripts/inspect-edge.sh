#!/usr/bin/env bash
set -euo pipefail
name="${1:?usage: inspect-edge.sh CONTAINER [MACHINE_ID]}"
machine_id="${2:-}"
docker inspect --format 'container={{.Name}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name"
docker logs --tail 120 "$name" 2>&1 | grep -E 'initialized|Connected to NATS|Subscribed|pending|ack_pending|ERROR|Traceback' || true
if [[ -n "$machine_id" ]]; then
  puda machine state "$machine_id" || true
  puda machine commands "$machine_id" || true
fi
