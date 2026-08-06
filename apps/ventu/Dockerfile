FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El código se monta como el paquete `ventu` (imports relativos internos).
COPY . /app/ventu
ENV PYTHONPATH=/app

EXPOSE 8080

# Railway inyecta $PORT; default 8080 en local.
CMD ["sh", "-c", "uvicorn ventu.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
