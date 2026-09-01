FROM alpine:3.21

RUN apk add --no-cache chrony \
    && mkdir -p /var/lib/chrony /run/chrony \
    && chown -R chrony:chrony /var/lib/chrony /run/chrony \
    && chmod 750 /run/chrony

COPY chrony.conf /etc/chrony/chrony.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 123/udp

# Entry point fixes /run/chrony at runtime (tmpfs). -d stays in the foreground;
# -s steps the clock at startup. SYS_TIME in compose.yml disciplines the host.
ENTRYPOINT ["/docker-entrypoint.sh"]

