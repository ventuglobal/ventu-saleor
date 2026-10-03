FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El paquete importable es `ventu_correo` (la carpeta con guion no es importable).
COPY ventu_correo /app/ventu_correo
ENV PYTHONPATH=/app

EXPOSE 8095

# Railway inyecta $PORT; 8095 en local.
CMD ["sh", "-c", "uvicorn ventu_correo.main:app --host 0.0.0.0 --port ${PORT:-8095}"]
