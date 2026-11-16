#!/usr/bin/env bash
set -euo pipefail
endpoint="${1:-127.0.0.1:4222}"
host="${endpoint%:*}"; port="${endpoint##*:}"
python3 - "$host" "$port" <<'PY'
import socket,sys
host,port=sys.argv[1],int(sys.argv[2])
with socket.create_connection((host,port),timeout=3) as s:
    banner=s.recv(512).decode('utf-8','replace').strip()
if not banner.startswith('INFO '): raise SystemExit('FAIL: no NATS INFO banner')
print('OK NATS handshake',host,port)
PY
