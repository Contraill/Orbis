# Orbis V1 operations and recovery

## Deployment contract

Use one backend Uvicorn worker and one replica. Delivery capabilities, compatibility
observations and Watch Together rooms are process-local. Rooms and resolved media
capabilities disappear on restart; clients reconnect/create rooms and resolve their
own media again. SQLite profile/history/library data remains durable.

The Docker entrypoint sets `umask 077`, applies `alembic upgrade head`, then starts
Uvicorn with one worker, 4096-byte WebSocket messages and queue depth 16. Migrations
must succeed before HTTP service starts. Do not start concurrent migration/app
replicas against the same SQLite file. SQLite connections enable foreign keys and
use a five-second busy timeout. No schema change is needed for this hardening;
current head is `e64a0c31f952`.

`.env.example` documents DATABASE_URL (default `sqlite:////data/media-app.db`),
TMDB_API_KEY, TMDB_LANGUAGE fallback, APP_ENV/APP_NAME, BUILD_ID and bounded
PROVIDER_OPERATION_TIMEOUT_SECONDS. TMDB/IMDb absence does not block startup.
Profile locale overrides metadata language. BUILD_ID contains only safe version
characters; `/api/admin/system` never returns environment variables or secrets.

Compose persists `./data:/data`, `./config:/config`, `./cache:/cache`, `./logs:/logs`.
Backend health probes `/api/health`; frontend probes the same endpoint through
nginx. Frontend startup waits for backend health. These checks show service/proxy
readiness, not external-provider availability. Restart policy remains unless-stopped.
The existing host port exposure is unchanged. This deployment assumes an already
trusted household/tailnet boundary; it does not add public ingress or TLS.

Admin provider settings are written atomically with mode 0600. The new umask
protects newly created files, but does not change pre-existing file permissions.
Restrict access to the host data/config directories and backup archives. Provider
Python is trusted owner code with container filesystem/network authority; its
validation subprocess is resource constrained, not a security sandbox. Never
activate untrusted Python expecting isolation.

## Backup contract

Back up these as one versioned recovery set:

1. The SQLite database: profiles/owner credential hash, preferences, durable viewing
   history/activity, resume state, My List/Not Interested, catalog and rating data.
2. The complete `config/` directory, especially provider `active.py`, drafts,
   override markers, `versions/` and `settings.json` secrets. Versions are retained
   configuration, not disposable cache.
3. `.env`, deployment configuration, the exact application release/image version
   and the recorded Alembic revision. Do not put secrets in Git or release bundles.

`cache/`, `logs/`, downloaded IMDb datasets and container layers are not necessary
for restoring user state. DB search/feed cache rows need no special backup, but it
is fine to include them in the whole DB; they expire/rebuild. Do not delete history
or library tables to reduce a backup. Resolved URLs, Watch Together rooms and
process-local observations are intentionally not recoverable.

For the simplest consistent backup, briefly stop writes (`docker compose stop`),
copy `data/`, `config/`, `.env` and `docker-compose.yml` into an owner-only backup
location, record the image/release and DB revision, then start the application.
Preserve any SQLite `-wal`/`-shm` sidecars with the stopped data directory. Keep
backups outside this repository, restrict/encrypt access, and test restoration.
Stopping services is an operator action, not performed by this milestone.

For an online DB-only snapshot, use SQLite's backup API (or sqlite3 `.backup`),
not a raw copy of a live database file. Quiesce provider editing while copying
config so DB/config describe a coherent installation. Example Python pattern:

```python
import sqlite3
with sqlite3.connect('file:/data/media-app.db?mode=ro', uri=True) as source:
    with sqlite3.connect('/backup/media-app.db') as target:
        source.backup(target)
```

The target must be a new, protected backup path, not the live database.

## Restore contract

Stop Orbis; restore the matching DB/config/.env recovery set into the configured
mounts and restore restrictive permissions. Start the same application version
first and verify profiles, My List, history and provider configuration. Confirm
`PRAGMA integrity_check` returns `ok` and `PRAGMA foreign_key_check` returns no rows.
Then make another backup before upgrading. Startup migrates old databases forward;
do not point an older application at a newer schema or assume downgrade is safe.
Restore the previous complete backup to roll back an incompatible deployment.
Existing installations without an owner password use `python -m core.owner`
inside the backend container (interactive local console); it revokes old owner
sessions. Stale client presence is cleaned automatically. Rooms must be recreated.

## Bounded maintenance and observability

| State | Bound / expiration |
| --- | --- |
| Delivery sessions | 256, at most 6h; source expiry enforced, 10min refresh grace; periodic/lazy purge |
| Registered relay resources | 4096/session, 32768 total, ancestry depth 8 |
| Compatibility observations | 1024, 15min non-sliding; lazy purge |
| Watch Together | 32 rooms, 8 participants; 30min idle, 6h maximum, closed retention 60s; sweep every 5s |
| Host / participant | Host reconnect grace 45s; participant stale 90s; deterministic connected fresh successor or close |
| Client presence | 256; stale after 2min, retained up to 1day; on-request + periodic cleanup |
| Search/feed cache | 2048 rows, hard insertion eviction; query TTL and feed 20min TTL; capacity can invalidate cursors early |
| Provider event log | Latest 10000 at insertion; 30-day TTL, bounded periodic batches |
| Owner sessions | Up to 10 issued sessions, 8h TTL; expired cleanup |

Every minute, maintenance removes at most 1000 expired rows per transient table
and bounded excess batches, cleans client presence and purges delivery sessions.
SQLite work runs in a thread, outside the room lock. A failed maintenance cycle
logs only the exception class and retries on the next cycle. Durable history,
catalog entities, provider versions and user intent are not TTL-deleted.

Use owner diagnostics for provider health/events, delivery mode/recovery evidence,
active sessions, recommendation explanations and room state. `/api/admin/system`
reports build/API version and limits. API responses are no-store. Uvicorn access
logs and nginx access/API error logs are disabled because resource paths contain
bearer capabilities; Uvicorn room paths are redacted. Application failure logs
omit URLs/credentials and do not log every media request. Retain startup/error
logs privately; reverse proxies added by operators must also avoid full capability
URLs. Active trusted provider code can itself print arbitrary secrets: core
sanitization cannot make arbitrary Python safe.
