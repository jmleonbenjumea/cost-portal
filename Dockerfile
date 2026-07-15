# cost-portal — panel de costes (Python puro, sin ODBC).
# Base fijada a bookworm por consistencia con siniestros-automation (Debian 13 "trixie"
# cambia la política de firmas de apt; aquí no usamos apt pero pinamos igual por estabilidad).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY . .

# No correr como root dentro del contenedor.
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser

# Escucha en el puerto del panel (PORTAL_PORT, por defecto 8001). Lo publica
# Plesk/nginx por HTTPS; nunca directo a internet (solo loopback en el compose).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORTAL_PORT:-8001} --workers 2"]
