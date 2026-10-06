# Contributing to Orbis

Orbis is licensed under [AGPL-3.0-only](LICENSE). By contributing, you agree
that your contribution may be distributed under that license. Discuss large
changes in an issue before implementation; V1 favors focused fixes over new
product architecture.

## Local setup

Copy `.env.example` to `.env`, supply your own TMDB key, then run
`docker compose up -d --build`. Never commit `.env`, databases, provider
credentials, device keys or logs. The first browser visit creates an owner
profile. The frontend lives in `app/frontend/`; the FastAPI backend lives in
`app/backend/`.

Run `npm ci`, `npm run build` and the directly relevant tests from
`app/frontend/` for frontend changes. Backend dependencies are pinned in
`app/backend/requirements.txt`; run the focused tests covering changed modules.
Use the neutral reference adapter and synthetic fixtures for provider work.

## Providers and security

The provider API is documented in [docs/provider-authoring.md](docs/provider-authoring.md).
Real-site provider implementations, credentials, cookies and captured media
URLs must stay outside the public repository in the private runtime provider
directory. Provider Python executes with backend privileges; review it as
trusted code. Report security issues privately as described in [SECURITY.md](SECURITY.md).

Keep public examples neutral, add focused tests for behavior changes, and
update user documentation when a visible contract changes. Do not include
downloaded movie artwork or playback streams in pull requests.
