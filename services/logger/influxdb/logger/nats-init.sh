#!/bin/sh
# Use the subscriber's NATS configuration, including optional TLS/E2EE settings.
# Checks the provisioned response streams and creates only missing ones with the
# protocol settings (interest, file, 24h); never updates or deletes a stream.
set -eu
exec /opt/puda/bin/python /opt/puda/subscriber.py --init-streams
