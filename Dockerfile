# İzmir MCP — read-only İzmir open-data MCP server.
#
# Deliberately lean: the ~141 MB GTFS timetable store (.data/) and the local
# virtualenv (.venv/) are never copied in. See .dockerignore. The store is
# rebuilt from the published EShot archive at run time into /data (rebuild tool:
# `python -m app.storage.gtfs_schedule`), so the image stays small and no stale
# timetable is baked into a layer.
#
# Pinned by digest (multi-arch python:3.11-slim index, resolved 2026-10-28) so a
# rebuild of this Dockerfile is reproducible.
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    IZMIR_MCP_HOST=0.0.0.0 \
    IZMIR_MCP_PORT=8000 \
    IZMIR_MCP_DATABASE_PATH=/data/izmir_mcp.sqlite3

WORKDIR /app

# Dependency layer first so application edits do not refetch wheels.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

# Container tooling (downloads the GTFS archive, writes /data). Ships with
# python:slim, no extra package needed.
COPY docker ./docker

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin izmir \
    && mkdir -p /data \
    && chown izmir:izmir /data
USER izmir

VOLUME ["/data"]
EXPOSE 8000

# /healthz is process liveness only; it does not touch upstream sources.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# HTTP transport. Stdio transport is available in the same image for clients
# that exec a one-shot process:
#   docker run --rm -i izmir-mcp python -m app.stdio
# Run with `python -m app.main` (module entrypoint) so the app object stays at
# app.main:app and the same module is importable by tooling and uvicorn alike.
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
