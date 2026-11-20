# syntax=docker/dockerfile:1
# API image. Build context is the repository root (see docker-compose.yml and .dockerignore).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY services/api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY services/api/app ./app

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Access logs come from RequestContextMiddleware (structured JSON), so uvicorn's are disabled.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
