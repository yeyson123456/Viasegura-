# Local risk worker (same engine as the Azure Function). Build context: repository root.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install pymongo==4.20.1
COPY services/functions/risk_engine ./risk_engine
RUN useradd --create-home --uid 10001 worker
USER worker
CMD ["python", "-m", "risk_engine.worker"]
