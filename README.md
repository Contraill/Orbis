# Orbis

Self-hosted, provider-agnostic media streaming platform.

## Status

Early development. The initial Docker bootstrap is operational.

## Stack

- React + TypeScript + Vite
- Python + FastAPI
- SQLite + SQLAlchemy + Alembic
- Docker Compose
- TMDB metadata
- Shaka Player

## Architecture

Orbis keeps the core application independent from individual content providers.
Providers are isolated, replaceable adapters behind the backend playback layer.

Core flow:

`Client -> Frontend -> FastAPI -> Playback Orchestrator -> Provider -> Playback Source`

TMDB is the canonical metadata and content identity source.

## Deployment

Designed primarily for Raspberry Pi 5 / CasaOS with remote access through Tailscale.

```sh
cp .env.example .env
docker compose up -d --build
```

The backend applies Alembic migrations before starting. Runtime databases, logs,
cache files, provider code, provider settings, and `.env` stay outside Git.

## Verification

Profile bootstrap, owner credential migration and library/activity contracts are
documented in [Profile and activity foundation](docs/profile-activity-foundation.md).
Existing installations must set their owner password locally with
`docker compose exec backend python -m core.owner` before using administration.

Run the backend suite against the application image:

```sh
docker run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL=sqlite:////tmp/media-app-tests.db \
  -v "$PWD/app/backend:/app" -w /app \
  media-app-backend:latest \
  python -m unittest discover -s tests -v
```

The frontend production build runs as part of `docker compose build`.

## License

Private project. No open-source license is currently granted.
