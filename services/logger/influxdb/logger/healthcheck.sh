#!/bin/sh
# Use the subscriber's NATS configuration, including optional TLS/E2EE settings.
set -eu
exec /opt/puda/bin/python /opt/puda/subscriber.py --healthcheck
