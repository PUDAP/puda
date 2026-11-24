FROM telegraf:1.39

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext-base python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/puda \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock /opt/puda-project/
RUN uv sync --project /opt/puda-project --python /usr/bin/python3 --frozen --no-dev --no-cache

COPY subscriber.py /opt/puda/subscriber.py
COPY telegraf.conf.template /etc/telegraf/telegraf.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY healthcheck.sh /healthcheck.sh
COPY nats-init.sh /nats-init.sh
RUN chmod +x /docker-entrypoint.sh /healthcheck.sh /nats-init.sh

HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD ["/healthcheck.sh"]

ENTRYPOINT ["/docker-entrypoint.sh"]
