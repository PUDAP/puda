#!/usr/bin/env bash
set -euo pipefail
ip -br addr
printf '
Routes:
'
ip route
printf '
NATS listeners:
'
ss -ltn | grep -E ':(4222|8222)\b' || true
