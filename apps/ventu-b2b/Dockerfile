FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ventu_b2b ./ventu_b2b

EXPOSE 8100
CMD ["sh", "-c", "uvicorn ventu_b2b.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
