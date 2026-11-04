# syntax=docker/dockerfile:1
# One image for the CLI, the run worker and the MCP servers, on a laptop and on Fargate
# (FR-15.3, architecture §17.2). Build from the repository root:
#
#   docker build -f docker/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t clay-sandbox .
#
# MCP servers are pre-installed at their pinned versions at build time, so nothing is installed
# over the network at run time (run with UV_OFFLINE=1, which the image sets).
# If a tool set uses `npx` servers, add: --build-arg WITH_NODE=true
FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG WITH_NODE=false

# The manifest records the commit even though .git is not in the image (FR-5.1).
ENV GIT_SHA=${GIT_SHA} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:/home/clay/.local/bin:$PATH

RUN if [ "$WITH_NODE" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends nodejs npm \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
 && useradd --create-home --uid 1000 clay \
 && mkdir /app && chown clay:clay /app

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

USER clay
WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY --chown=clay:clay pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=clay:clay . .
RUN uv sync --frozen --no-dev

# Fill the MCP server caches (no-op until the tool sets exist), then forbid network installs.
RUN python docker/preinstall_mcp.py toolsets
ENV UV_OFFLINE=1

# No credentials are baked in: pass AWS_* variables or use the Fargate task role.
ENTRYPOINT ["clay-sandbox"]
