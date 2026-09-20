# Media App

Self-hosted, provider-agnostic media streaming platform.

## Status

Early development. The initial Docker bootstrap is operational.

## Stack

- React + TypeScript + Vite
- Python + FastAPI
- SQLite + SQLAlchemy + Alembic
- Docker Compose
- TMDB metadata
- Shaka Player (planned)

## Architecture

Media App keeps the core application independent from individual content providers.
Providers are isolated, replaceable adapters behind the backend playback layer.

Core flow:

`Client -> Frontend -> FastAPI -> Playback Orchestrator -> Provider -> Playback Source`

TMDB is the canonical metadata and content identity source.

## Deployment

Designed primarily for Raspberry Pi 5 / CasaOS with remote access through Tailscale.

## License

Private project. No open-source license is currently granted.
