#!/bin/sh
set -e

PREFIX="${MACHINE_PREFIX:-test}"

if [ -n "$MACHINE_IDS" ]; then
  exec uv run python main.py --ids "$MACHINE_IDS"
fi

if [ -n "$COUNT" ] && [ "$COUNT" -gt 1 ]; then
  exec uv run python main.py --count "$COUNT" --prefix "$PREFIX"
fi

if [ -z "$MACHINE_ID" ]; then
  replica="${HOSTNAME##*-}"
  case "$replica" in
    ''|*[!0-9]*) replica=1 ;;
  esac
  export MACHINE_ID="${PREFIX}-${replica}"
fi

exec uv run python main.py --id "$MACHINE_ID"
