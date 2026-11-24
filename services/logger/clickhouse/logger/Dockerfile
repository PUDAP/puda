FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && uv cache clean \
    && groupadd --gid 10001 logger \
    && useradd --uid 10001 --gid logger --no-create-home logger
COPY storage.py subscriber.py ./
USER 10001:10001
ENTRYPOINT ["python", "subscriber.py"]
