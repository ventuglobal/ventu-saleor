FROM python:3.12-slim

WORKDIR /app

# Deps del reactor + del emisor (facturador_v2/boleta_bot).
COPY requirements.txt requirements-emitter.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-emitter.txt \
    && python -m playwright install --with-deps chromium

# Paquete de la app + paquetes vendorizados (importables desde /app).
COPY ventu_facturacion /app/ventu_facturacion
COPY vendor /app/vendor
ENV PYTHONPATH=/app:/app/vendor

EXPOSE 8095

# Railway inyecta $PORT; default 8095 en local.
CMD ["sh", "-c", "uvicorn ventu_facturacion.main:app --host 0.0.0.0 --port ${PORT:-8095}"]
