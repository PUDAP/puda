#!/bin/sh
set -e

# /run is often a fresh tmpfs. chronyd 4.x requires /run/chrony owned by the
# dropped-privilege user with mode 0750, or it disables the command socket.
mkdir -p /run/chrony /var/lib/chrony
chown -R chrony:chrony /run/chrony /var/lib/chrony
chmod 750 /run/chrony

exec chronyd -d -s
