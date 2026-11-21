FROM python:3.12-slim

# Don't write .pyc files; print logs immediately (no buffering) so `docker compose logs` is live
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Borrow the uv binary from its official image (same tool you use locally, much faster than pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy requirements FIRST and install, THEN copy code.
# Docker caches each step: editing code won't re-install dependencies, so rebuilds take seconds.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app ./app

# Never run as root inside a container
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
