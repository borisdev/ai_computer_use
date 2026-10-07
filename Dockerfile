# The agent, containerised — so the RENDERING STACK is pinned, not the host's.
#
# ⛔ THIS IS THE FIX FOR issue 0012, AND IT IS THE REASON THIS FILE EXISTS.
# A visual locator is a template PNG matched at threshold 0.95. Those crops
# were rasterised by Linux Chromium; macOS Chromium hints and antialiases text
# differently, so the same control is different pixels. On an M1 Mac the first
# control of the first screen scored 0.6889 and the run escalated to a human —
# correctly, and uselessly for a reviewer trying to see the demo.
#
# Recording `captured_on` (also 0012) makes that legible. It does not make a
# map portable. Pinning the stack does: every host that runs the agent in here
# drives the SAME Linux Chromium the committed templates came from, so the
# host leaves the path entirely.
#
# Same rationale as recording the environment on the map — a reader, a
# reviewer and a future developer should not have to discover that the
# rasteriser was an input.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ⚠️ THE VENV LIVES OUTSIDE /app ON PURPOSE. compose bind-mounts the repo over
# /app so artifacts and evidence land on the host — which would shadow a
# .venv built here and leave the container running the host's, for the host's
# platform. This is the whole reason the image can be trusted.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first, so editing source does not re-resolve them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# The browsers are already in the base image at $PLAYWRIGHT_BROWSERS_PATH, and
# the tag is pinned to the SAME playwright version as uv.lock (1.63.0). A
# mismatch here is not a warning — Playwright refuses to launch.
ENTRYPOINT ["banking-jobs"]
CMD ["--help"]
