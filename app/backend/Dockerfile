FROM node:24-bookworm-slim AS webos-cli
RUN npm install --global --no-audit --no-fund @webos-tools/cli@3.2.6

FROM python:3.13-slim

COPY --from=webos-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=webos-cli /usr/local/lib/node_modules/@webos-tools/cli /usr/local/lib/node_modules/@webos-tools/cli
RUN ln -s /usr/local/lib/node_modules/@webos-tools/cli/bin/ares-setup-device.js /usr/local/bin/ares-setup-device \
    && ln -s /usr/local/lib/node_modules/@webos-tools/cli/bin/ares-novacom.js /usr/local/bin/ares-novacom \
    && ln -s /usr/local/lib/node_modules/@webos-tools/cli/bin/ares-device.js /usr/local/bin/ares-device \
    && ln -s /usr/local/lib/node_modules/@webos-tools/cli/bin/ares-launch.js /usr/local/bin/ares-launch \
    && ln -s /usr/local/lib/node_modules/@webos-tools/cli/bin/ares-install.js /usr/local/bin/ares-install

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["sh", "-c", "umask 077 && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --ws-max-size 4096 --ws-max-queue 16"]
