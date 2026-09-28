FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ventu_b2b ./ventu_b2b
EXPOSE 8100
# --proxy-headers con --forwarded-allow-ips='*': detrás del proxy de Railway la
# IP del proxy no es fija, y sin confiar en ella uvicorn ignora
# X-Forwarded-Proto/For (por defecto solo confía en 127.0.0.1). El comillado
# simple evita que sh expanda el asterisco como glob; ${PORT:-8100} sí se
# expande, porque va dentro de `sh -c`. La URL del manifest no depende de esto:
# `_base_publica` lee los encabezados por su cuenta (ver main.py).
CMD ["sh", "-c", "uvicorn ventu_b2b.main:app --host 0.0.0.0 --port ${PORT:-8100} --proxy-headers --forwarded-allow-ips='*'"]
