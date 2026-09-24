FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["sh", "-c", "umask 077 && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --ws-max-size 4096 --ws-max-queue 16"]
