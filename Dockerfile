# ghcr.io/archangelic/pinhook: pinhook on Python's slim image, as a non-root user.
#
# /bot is bot_dir. Mount the config at /bot/config.yaml, read-only, and a volume at
# /bot/data. Plugins and recipes go in /bot/plugins and /bot/recipes, mounted or baked
# into an image built on this one. Logs go to stdout, and the health endpoint is on 8080.

FROM python:3.15-slim AS build
COPY . /src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /dist /src

FROM python:3.15-slim
COPY --from=build /dist /dist
RUN pip install --no-cache-dir /dist/*.whl && rm -r /dist \
    && useradd --system --uid 10001 --home-dir /bot --shell /usr/sbin/nologin pinhook \
    && mkdir -p /bot/plugins /bot/recipes /bot/data \
    && chown pinhook:pinhook /bot/recipes /bot/data

# defaults for options the config leaves out, which it can still set
ENV PINHOOK_BOT_DIR=/bot \
    PINHOOK_LOG_FILE=- \
    PINHOOK_HEALTH_PORT=8080 \
    PINHOOK_HEALTH_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

WORKDIR /bot
USER pinhook
VOLUME /bot/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]
CMD ["pinhook", "run", "/bot/config.yaml"]
