# Orbis

Self-hosted, provider-agnostic media streaming platform.

## Status

Backend V1 hardening is complete; final frontend design is the next milestone.
Start with the [V1 architecture/API index](docs/backend-v1.md),
[verification report](docs/v1-hardening-report.md), and
[backup/deployment contract](docs/v1-operations.md).

## Stack

- React + TypeScript + Vite
- Python + FastAPI
- SQLite + SQLAlchemy + Alembic
- Docker Compose
- TMDB metadata
- Shaka Player

## Architecture

Orbis keeps the core application independent from individual content providers.
Providers are replaceable adapters behind the backend playback layer. Live
provider Python is trusted owner code, not a security sandbox.

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

## Provider authoring and public boundary

Use the [neutral provider-authoring guide](docs/provider-authoring.md).
The [post-freeze provider audit](docs/provider-public-readiness-audit.md) records
the current private adapter inventory and the migration required before publication.
example-provider remains private-installation factory source until that reviewed migration;
this repository is not yet approved for public distribution.

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
