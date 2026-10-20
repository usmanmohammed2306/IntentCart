FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=4000 DATABASE_PATH=/app/var/intentcart.sqlite3
WORKDIR /app
COPY requirements.lock.txt /app/
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --create-home appuser
COPY intentcart /app/intentcart
COPY scripts/*.py /app/scripts/
COPY docs/protocols /app/docs/protocols/
RUN mkdir /app/var && chown -R appuser:appuser /app
USER appuser
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/healthz', timeout=3)"
CMD ["python", "-m", "intentcart"]
