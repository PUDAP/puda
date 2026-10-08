#!/bin/sh
# Write one CA and a server certificate for each of the three TLS nodes.
# Fill nats1/.env, nats2/.env, and nats3/.env before running this.
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

read_env() {
  dir=$1
  file=$dir/.env
  if [ ! -f "$file" ]; then
    file=$dir/.env.example
  fi
  HOST_IP=
  # shellcheck disable=SC1090
  set -a
  . "$file"
  set +a
  printf '%s' "$HOST_IP"
}

san_for() {
  host=$1
  san="DNS:localhost,IP:127.0.0.1"
  case "$host" in
    ''|127.0.0.1|localhost) ;;
    *[0-9].*[0-9]*) san="$san,IP:$host" ;;
    *) san="$san,DNS:$host" ;;
  esac
  printf '%s' "$san"
}

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
  -keyout "$tmpdir/ca.key" -out "$tmpdir/ca.pem" \
  -subj "/CN=puda-nats-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

for node in nats1 nats2 nats3; do
  host=$(read_env "$node")
  san=$(san_for "$host")
  mkdir -p "$node/certs"
  openssl req -newkey rsa:2048 -nodes \
    -keyout "$node/certs/server.key" -out "$tmpdir/server.csr" \
    -subj "/CN=$node"
  printf 'subjectAltName=%s\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth,clientAuth\n' "$san" > "$tmpdir/server.ext"
  openssl x509 -req -in "$tmpdir/server.csr" \
    -CA "$tmpdir/ca.pem" -CAkey "$tmpdir/ca.key" -CAcreateserial \
    -out "$node/certs/server.pem" -days 825 -extfile "$tmpdir/server.ext"
  cp "$tmpdir/ca.pem" "$node/certs/ca.pem"
  chmod 600 "$node/certs/server.key"
  echo "Wrote $node/certs for $host"
done

echo "Give clients any node's certs/ca.pem as PUDA_NATS_CA."
echo "Do not copy server.key files off their NATS hosts, and do not put the lab key here."
