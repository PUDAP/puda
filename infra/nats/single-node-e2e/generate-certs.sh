#!/bin/sh
# Write a local CA and server certificate for the single-node TLS broker.
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  . ./.env
  set +a
fi

HOST_IP=${HOST_IP:-127.0.0.1}
mkdir -p certs

if [ ! -f certs/ca.key ]; then
openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
  -keyout certs/ca.key -out certs/ca.pem \
  -subj "/CN=puda-nats-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
fi

san="DNS:localhost,IP:127.0.0.1"
case "$HOST_IP" in
  ''|127.0.0.1|localhost) ;;
  *[0-9].*[0-9]*) san="$san,IP:$HOST_IP" ;;
  *) san="$san,DNS:$HOST_IP" ;;
esac

openssl req -newkey rsa:2048 -nodes \
  -keyout certs/server.key -out certs/server.csr \
  -subj "/CN=puda-nats"
cat > certs/server.ext <<EOF
subjectAltName=$san
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
EOF
openssl x509 -req -in certs/server.csr \
  -CA certs/ca.pem -CAkey certs/ca.key -CAcreateserial \
  -out certs/server.pem -days 825 -extfile certs/server.ext
rm -f certs/server.csr certs/server.ext
chmod 600 certs/ca.key certs/server.key
echo "Wrote certs/ca.pem and certs/server.pem (SAN: $san)"
echo "Give clients certs/ca.pem as PUDA_NATS_CA. Do not copy certs/server.key off this host."
