# ARADA platform image: one image, several process roles (ADR-001).
#
# Multi-stage: uv (a build tool) exists only in the builder. The runtime stage
# receives the application and its virtualenv, nothing else, so build tooling
# and its dependencies are not part of the shipped attack surface.
FROM ghcr.io/astral-sh/uv:0.11.15 AS uv

FROM python:3.12-slim-bookworm AS build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
# Dependencies first (cached layer), strictly from the lockfile.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=build /app /app
RUN useradd --system --uid 10001 --no-create-home arada \
 && chown -R root:root /app && chmod -R a-w /app
USER arada
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "--factory", "arada.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
