# BDC Portfolio Parser — container image with the LLM layer wired up.
#
# Mount points:
#   /app/raw   — cached EDGAR HTML (bind-mount from host so `fetch` is one-time)
#   /app/data  — pipeline outputs (CSV + JSON), bind-mount to persist on host
#
# Secrets:
#   EDGAR_IDENTITY (required) and provider API keys (optional) come from
#   .env via docker-compose's env_file. They are never baked into the image.
#
# Usage (via docker compose):
#   docker compose build
#   docker compose run --rm bdc-parse fetch FDUS
#   docker compose run --rm bdc-parse schedule FDUS

FROM python:3.12-slim

# Faster, deterministic, no .pyc clutter inside the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Only the files pip needs to install the package — keeps the build cache hot.
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install with the LLM extra so the regex-first / LLM-fallback path works
# out of the box when an API key is provided via env_file at runtime.
RUN pip install -e ".[anthropic]"

# Document the bind-mount points for `docker run -v` users; harmless under
# docker compose where the same paths are declared in docker-compose.yml.
VOLUME ["/app/raw", "/app/data"]

ENTRYPOINT ["bdc-parse"]
CMD ["--help"]
