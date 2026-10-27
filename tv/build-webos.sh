#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3 tv/build.py
docker run --rm -v "$PWD/tv/dist:/work" node:24.22.1-bookworm-slim sh -c \
  'npm install --global --no-audit --no-fund @webos-tools/cli@3.2.6 >/dev/null && ares-package --no-minify -o /work /work/webos/app'
mv tv/dist/com.contraill.orbis_1.0.0_all.ipk tv/dist/orbis-webos-1.0.0.ipk
echo "tv/dist/orbis-webos-1.0.0.ipk"
