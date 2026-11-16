#!/usr/bin/env bash
set -euo pipefail
for cmd in git docker python3 puda; do
  if command -v "$cmd" >/dev/null 2>&1; then printf 'OK command %s: %s
' "$cmd" "$(command -v "$cmd")"; else printf 'MISSING command %s
' "$cmd"; fi
done
printf 'UTC: '; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'Disk: '; df -h --output=avail . | tail -n 1 | xargs
if docker info >/dev/null 2>&1; then echo 'OK Docker daemon'; else echo 'FAIL Docker daemon access'; fi
