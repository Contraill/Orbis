# Episode lifecycle, client capabilities and basic sessions

This milestone extends the existing playback state, canonical catalog and delivery
broker. Client presence is transient telemetry; it is not another watch-history
store. Recommendation scoring, catalog identity and provider implementations are
unchanged.

## Episode API

The following endpoints extend
`/api/playback/profiles/{profile_id}/tv/{tmdb_id}/season/{season}/episode/{episode}`:

| Endpoint | Contract |
| --- | --- |
| `GET /lifecycle?enrich=false` | Canonical current/previous/next references, localized titles, air dates, boundary/final flags, current resume position, autoplay preference and optional markers. |
| `POST /prepare-next` | Resolves a playable next episode without creating/updating its playback state or viewing history. Returns `preparation_only=true`. |
| `POST /transition` | Body: `direction` (`next` or `previous`), optional `prepared_source_session_id`. Activates the destination and returns the existing playback-session contract. |

`next_status` is `available`, `unreleased`, `series_finished` or
`metadata_incomplete`. Only an explicitly ended/canceled series with known final
season and episode counts produces `series_finished`. Missing catalog rows are
not proof of completion. Unknown/future air dates prevent automatic preparation
and transition. Specials do not automatically advance to the regular seasons.

The optional enrichment path uses the existing 24-hour localized metadata cache
and fetches only series details, the current season and necessary neighboring
seasons. It degrades to cached metadata with a warning if TMDB is unavailable.
English and Turkish metadata retain their separate cache records.

Autoplay is a client action authorized by the latest `autoplay_allowed` value;
the backend does not run a playback timer. Manual next/previous remains usable
with autoplay disabled. Destination resume state is retained. Logical provider,
host/source, quality, audio and subtitle preferences carry forward, with existing
fallback if unavailable. No player-specific variant IDs are persisted.

Prepared sources are reusable only when identity, client, audience, preferences,
capabilities and source freshness still match. Otherwise transition resolves
normally. Preparation neither changes the active client's current episode nor
creates a watch event. Actual state saves continue to own activity/history.

## Optional markers

Migration `e64a0c31f952` adds `content_markers`, keyed by canonical episode content
key. Its normalized JSON fields are `intro_start`, `intro_end`, `recap_start`,
`recap_end`, `credits_start`, `credits_end`, in seconds. Each may be null; a range
with both ends must have a strictly later end. Values must be finite and
nonnegative. Source/provenance and update time are retained.

Owner-authorized `PUT /api/admin/episode-markers/tv/{id}/season/{s}/episode/{e}`
accepts these fields and a required `source`. There is no detection, fabricated
timestamp, media analysis or skip-button UI. Lifecycle responses expose the data
needed for future Skip Intro/Recap and credits-driven Next Episode controls.

## Capabilities and quality

`ClientCapabilities` reports HLS/DASH support, video/audio codec families,
`max_height`, text-track support/formats and optional HDR support. Unknown codec
or HDR metadata remains unknown; no device database or transcoder is added.
Missing capabilities preserve legacy selection/delivery behavior.

Known incompatible sources are excluded before existing preference ranking.
Direct-file heights, reported codecs and HDR flags participate in eligibility.
For HLS, the master label is not confused with its lower variants: bounded
manifest discovery lists compatible heights, and the broker relays/re-writes
root and child manifests to remove incompatible variants before registering
their resource URLs. Segment/key delivery still follows the adaptive broker's
existing policy. Shaka also receives the practical maximum height restriction.

Auto retains adaptive bitrate selection within compatible variants. Explicit
height preferences remain logical preferences and use existing nearest-height
fallback. Responses include `quality_outcome`: `auto`, `exact`,
`unavailable_fallback`, `incompatible_fallback` or `unverified`, plus
`max_compatible_height`. No eligible source returns HTTP 409 with normalized
`no_compatible_source` / `no_compatible_variant` diagnostics.

## Client presence

Migration `e64a0c31f952` also adds `client_sessions`, indexed by profile and last
seen. It stores a random session ID, profile, cookie audience, display name/type,
capabilities, creation/last-seen/start/stop/revoke times, current canonical content
identity, source-session association, position and state.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/sessions` | Register `profile_id`, `display_name`, optional client type and capabilities. |
| `GET /api/sessions/{id}` | Cookie-bound current client presence. |
| `PATCH /api/sessions/{id}` | Heartbeat/state/position, optional capability update; playing/paused requires that client's currently active source. |
| `DELETE /api/sessions/{id}` | Revoke own session and its retained delivery sources. |
| `GET /api/admin/sessions?limit=64` | Owner-only bounded recent/active session visibility. |
| `DELETE /api/admin/sessions/{id}` | Owner-only termination/revocation. |

Registered clients send `X-Orbis-Session` on profile playback requests. The
session must match the profile and HTTP-only playback audience cookie. Ordinary
legacy playback requests without a registered client still work. Profiles are
not authentication accounts. Admin authorization remains the existing owner
credential, never a selected profile ID.

Resolve/recovery/transition binds current content and source; heartbeats do not
write playback state or history. Completion clears presence without destroying
prepared-next sources. Stale stop notifications from a previous source cannot
stop its replacement. Revocation invalidates associated in-memory sources.

Cleanup is request-driven: over two minutes without presence makes an active
session stale; records older than a day are removed. At most 256 recent records
are retained. The frontend sends 30-second heartbeats and saves durable progress
before sending a stop. Idle browser tabs are not kept alive indefinitely.

These contracts provide future Watch Together with participant session/profile,
canonical episode identity, play/pause state and timeline position. No rooms,
WebSockets, shared clock, remote playback commands or synchronization exist yet.

## Minimal verification frontend

The existing player gains previous/next controls, explicit Prepare Up Next,
autoplay preference, boundary/final status, optional marker diagnostics and a
client-capability/session panel with a practical resolution override. Existing
quality controls display the normalized outcome. `/admin/sessions` lists recent
clients and permits owner termination. This is not a player redesign.

## Limits

- Compatibility is constrained by provider/manifest metadata. Undeclared codecs
  cannot be guaranteed compatible without playback. DASH has protocol/source
  eligibility and player restrictions, but no new MPD parser/rewriter.
- HLS quality discovery remains best effort and bounded by the existing timeout
  and manifest-size limit. Unknown qualities are reported as unverified.
- A paused/background client that misses the two-minute timeout must resolve
  playback again. Cleanup happens on session/playback requests, not a daemon.
- Revocation stops future API/relay use and the web client reacts to heartbeat
  rejection; already buffered media or an already-issued direct upstream URL
  cannot be recalled. This is visibility, not DRM or device enforcement.
- Preparations share the bounded in-process source registry and do not survive
  process restart. No schema stores upstream URLs or player variant IDs.
- Marker timestamps require an explicit trusted/manual source. Episode ordering
  follows TMDB season/episode numbers; alternate/DVD order is not implemented.

The recommended next milestone is basic Watch Together coordination using these
session and canonical playback contracts, with timeline synchronization tested
separately from providers, history and recommendation ranking.

## Verification (2026-09-23)

- Full backend suite: 150 tests passed in one broad run, including fresh/legacy
  migrations and Alembic drift checks. A subsequent concurrent-revocation fix
  passed the expanded 16-test episode/client suite (one additional regression).
- Existing playback tests: 25 passed; delivery broker tests: 20 passed.
- A SQLite backup of the actual existing installation was upgraded separately;
  every pre-existing table's row count was preserved, new session/marker tables
  were empty and `alembic check` reported no new operations. The original DB was
  mounted read-only and not migrated.
- Frontend TypeScript and Vite production build passed. Existing React Router
  directive and Shaka chunk-size warnings remain non-fatal.
- Both production Dockerfiles built for ARM64. Isolated containers started
  without publishing ports: Uvicorn health/fresh empty profile list passed;
  nginx configuration and frontend HTTP response passed on aarch64.
- Offline image builds initially lacked matching build-cache layers; normal
  Docker build networking reused the available dependency layers successfully.
- `git diff --check` passed. No new runtime dependency was added.
- Live-provider and browser playback tests were not run. `agent-browser` and a
  local Chromium installation were unavailable; type/build and backend tests do
  not replace a later manual/browser autoplay and codec smoke test.

Primary modules: `playback/episodes.py`, `playback/capabilities.py`,
`client_sessions/service.py`, `api/episodes.py`, `api/client_sessions.py`, the
existing playback choices/service/delivery/HLS modules, new client-session DB
models/migration, `tests/test_episode_clients.py`, and the frontend API/player/
playback page plus `admin/SessionsPage.tsx`.
