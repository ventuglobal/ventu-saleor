FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El paquete importable es `ventu_pagos` (la carpeta con guion no es importable).
COPY ventu_pagos /app/ventu_pagos
ENV PYTHONPATH=/app

EXPOSE 8090

# Railway inyecta $PORT; default 8090 en local (distinto de ventu-sync:8080).
CMD ["sh", "-c", "uvicorn ventu_pagos.main:app --host 0.0.0.0 --port ${PORT:-8090}"]
