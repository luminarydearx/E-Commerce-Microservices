FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && \
    useradd -u 10001 -m appuser
RUN pip install --no-cache-dir \
    "fastapi==0.111.0" "uvicorn[standard]==0.30.1" "pydantic==2.8.2" \
    "pydantic-settings==2.3.4" "redis==5.0.7" "kafka-python==2.0.2" \
    "elasticsearch>=8.14.0,<9.0.0" "prometheus-client==0.20.0" "httpx==0.27.0"
COPY --chown=appuser:appuser . /app
USER appuser
EXPOSE 8012
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8012/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012", "--workers", "2"]
