FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INTAKEGUARD_DB=/data/intakeguard.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY intakeguard ./intakeguard
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'))"
CMD ["sh", "-c", "uvicorn intakeguard.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
