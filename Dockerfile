# İzmir MCP — read-only İzmir open-data MCP server.
#
# Deliberately lean: the ~141 MB GTFS timetable store (.data/) and the local
# virtualenv (.venv/) are never copied in. See .dockerignore. The store is
# rebuilt from the published EShot archive at run time into /data (rebuild tool:
# `python -m app.storage.gtfs_schedule`), so the image stays small and no stale
# timetable is baked into a layer.
#
# Both stages are pinned by digest (multi-arch python:3.11-slim index, resolved
# 2026-10-28) so a rebuild of this Dockerfile is reproducible.

# --- builder: hashed, locked dependencies into a venv, then the app wheel ----
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
# Dependency layer first: it only changes when the lockfile does, so app edits
# reuse the cached wheels. --require-hashes rejects anything not in the lock.
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
# setuptools is only the build backend; its vendored jaraco.context/wheel carry
# HIGH CVEs (trivy) and nothing imports it at run time.
RUN pip install --no-deps . \
    && pip uninstall -y setuptools

# --- runtime: venv + container tooling only, non-root ------------------------
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

ARG VERSION=0.1.0
LABEL io.modelcontextprotocol.server.name="io.github.zexy2/izmir-mcp" \
      org.opencontainers.image.title="izmir-mcp" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/zexy2/izmirmcp" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    IZMIR_MCP_HOST=0.0.0.0 \
    IZMIR_MCP_PORT=8000 \
    IZMIR_MCP_DATABASE_PATH=/data/izmir_mcp.sqlite3 \
    IZMIR_MCP_GTFS_DATABASE_PATH=/data/izmir_mcp_gtfs.sqlite3

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# Container tooling (downloads the GTFS archive, writes /data). Ships with
# python:slim, no extra package needed.
COPY docker ./docker

# Same for the base image's system interpreter: the app runs from /opt/venv.
RUN /usr/local/bin/python -m pip uninstall -y --no-cache-dir setuptools wheel \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin izmir \
    && mkdir -p /data \
    && chown izmir:izmir /data
USER izmir

VOLUME ["/data"]
EXPOSE 8000

# /healthz is process liveness only; it does not touch upstream sources.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# HTTP transport. 0.0.0.0 is the in-container bind; set IZMIR_MCP_API_KEYS and
# IZMIR_MCP_ALLOWED_HOSTS before publishing the port (app.main warns otherwise).
# Stdio transport is available in the same image for clients that exec a
# one-shot process:
#   docker run --rm -i -e IZMIR_MCP_SKIP_GTFS_BUILD=1 izmir-mcp izmir-mcp stdio
#   docker run --rm -i izmir-mcp python -m app.stdio
# Run with `python -m app.main` (module entrypoint) so the app object stays at
# app.main:app and the same module is importable by tooling and uvicorn alike.
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
