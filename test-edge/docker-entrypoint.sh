#!/bin/sh
set -e

if [ -n "$1" ]; then
  exec uv run python main.py "$@"
fi

if [ -n "$MACHINE_ID" ]; then
  exec uv run python main.py --id "$MACHINE_ID"
fi

exec uv run python main.py
