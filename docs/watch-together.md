# Watch Together backend

Watch Together coordinates playback intent and a canonical timeline for a small
home server. Each participant resolves media and saves progress through their own
profile/client session. A room never contains a provider URL, source session ID,
relay capability, provider headers, credentials or provider implementation code.
Recommendations and meaningful activity aggregation are unchanged.

## Model and deployment

`watch_together/domain.py` provides the transport-independent room state machine,
clock injection and centralized `Policy`. `api/watch_together.py` supplies HTTP
membership/private resolution and WebSocket authentication/broadcasting.

Rooms are ephemeral, in-memory and single-process, like the existing delivery
source registry. The backend Docker command explicitly uses **one Uvicorn worker**.
Do not run multiple backend replicas/workers without replacing this store and
broadcast mechanism. Restarting the backend ends rooms; a short socket disconnect
does not. No database migration or new dependency is needed.

A room contains a 192-bit opaque ID, host participant ID, canonical movie or TV
season/episode identity, paused/playing state, anchored position/time, rate
(currently 1x), revision, content revision, creation/activity timestamps, status
and participants. Each participant privately maps an opaque participant ID to an
existing client session/profile, connection generation, readiness and timestamps.
Public snapshots expose profile ID/name and opaque participant ID, not the client
session credential. Internal previous/resolved content references preserve each
participant's own logical playback preferences across content transitions.

Default bounds/policies:

| Setting | Default |
| --- | --- |
| Rooms / participants per room | 32 / 8 |
| Host reconnect grace | 45 seconds after disconnection |
| Participant heartbeat timeout | 90 seconds |
| Disconnected participant retention | 90 seconds after disconnection |
| Idle room / absolute room lifetime | 30 minutes / 6 hours |
| Closed room retention | 60 seconds |
| Cleanup cadence | 5 seconds, plus request-time cleanup |
| Incoming JSON / outgoing queue | 4096 bytes / 16 messages per connection |
| Event rate | 10/second with a burst of 20 |

A host reconnect within grace retains authority. After grace, the earliest joined
**connected** participant becomes host; opaque participant ID breaks equal-time
ties deterministically. With no eligible successor, the room closes and pauses.
Explicit host leave promotes/closes immediately. A delayed old socket cannot
mark its replacement disconnected. The lifespan janitor also expires abandoned
rooms when no further requests arrive.

## HTTP contract

All HTTP operations require the existing HTTP-only `playback_client` cookie and
`X-Orbis-Session` header. Profile/session validation is reused from basic sessions.
Responses are `Cache-Control: no-store`.

| Endpoint | Body / result |
| --- | --- |
| `POST /api/watch-together/rooms` | `{content, position?: 0}`; returns room snapshot and own `participant_id`. |
| `POST /api/watch-together/rooms/{id}/join` | Idempotent for an existing member/session; returns snapshot and own participant ID. |
| `GET /api/watch-together/rooms/{id}` | Member-only current snapshot. |
| `POST /api/watch-together/rooms/{id}/resolve` | `{content_revision}`; privately returns `{playback, room}` for this participant only. |

A client session can belong to only one open room. A profile can still use
multiple distinct client sessions. Content is validated as:

```json
{"media_type":"movie","tmdb_id":42}
```

or:

```json
{"media_type":"tv","tmdb_id":42,"season_number":1,"episode_number":2}
```

Movies reject episode fields; TV requires season and episode. IDs/positions are
validated, finite and nonnegative where applicable. A room's content identity is
independent of metadata locale and does not assert source availability.

## WebSocket protocol

Connect to `/api/watch-together/rooms/{id}/ws` **after HTTP create/join**. Authenticate
within ten seconds with a first JSON message:

```json
{"session_id":"existing-client-session-id"}
```

The session secret is not placed in the WebSocket URL/logs. Cookie ownership,
non-revocation and existing room membership are required. Browser Origin must
match the request Host; native clients may omit Origin. Revocation is rechecked
on traffic and at most five-second receive intervals. Binary frames are rejected.

Server messages:

- `welcome`: own participant ID.
- `state`: complete room snapshot including `revision`, `content_revision`,
  `host_id`, canonical content, projected `position`, `state`, `rate`, server time,
  lifecycle timestamps/status and participants/readiness. Join, connect, leave,
  ready, host change, playback changes and close are broadcast as snapshots.
- `sync`: private correction advice for the reporting participant; never broadcast
  as another playback command.
- `error`: stable code such as `host_only`, `stale_revision`, `invalid_event` or
  `next_episode_unavailable`. Revision conflicts include a fresh snapshot.
- `replaced`: a newer connection for this participant superseded this socket.

All subsequent client events carry the last accepted `revision`:

```json
{"type":"play","revision":7}
{"type":"pause","revision":8,"position":120.5}
{"type":"seek","revision":9,"position":300}
{"type":"position","revision":10,"position":300.2,"rate_supported":true}
{"type":"ready","revision":10}
{"type":"next_episode","revision":11}
```

Supported types are `ready`, `play`, `pause`, `seek`, `position`, `content`,
`next_episode`, `preferences_changed`, `leave`, `close`. Only the host may change
play/pause/seek/content or close the room. Non-hosts do not request/vote on control
in v1. `content` requires a canonical `content` object. `seek`/`position` require
position; play/pause may omit it to use the projected timeline. Other fields,
including transport URLs, are rejected.

The server serializes mutations and assigns increasing revisions. Commands must
match the current revision exactly; duplicate/stale commands cannot reapply an
old seek/transition. Position reports do not change canonical state/revision and
produce private drift advice. Repeated ready is idempotent. `content_revision`
changes only for content changes, allowing source resolution to finish while
readiness/join events advance the ordinary revision. A stale resolved episode is
discarded if the room changed/closed or the participant left/revoked meanwhile.

Slow consumers cannot stall the room: outgoing bounded queues coalesce to newer
full snapshots; failed/slow sends terminate the connection. The client must treat
snapshots as state, not replay them as commands. nginx now forwards the WebSocket
Upgrade/Connection headers; no host networking configuration is changed.

## Timeline and drift

The server projects playing position from its anchor and elapsed server time.
Paused position does not advance. Position reports from any participant are
observations, not authority to change the anchor.

| Drift | Advice |
| --- | --- |
| Playing, at most 250 ms | No correction |
| Playing, 250 ms to under 2 s | Temporary 0.97x or 1.03x when supported |
| Playing, at least 2 s | Seek to canonical position |
| Paused, over 50 ms | Seek exactly to canonical position |

Rate advice expires after five seconds; subsequent reports may renew it. Clients
without rate support leave small drift alone and seek only beyond the large-drift
threshold. Capabilities never alter the canonical room timeline. The minimal web
client reports every two seconds and suppresses echoes from applied corrections.

## Playback, transitions and history

Private room resolution calls the existing provider/source/quality selection,
capability checks and adaptive broker. A participant can use Moly/900p while
another uses DBX/720p; readiness and intent are the only shared coordination.
`preferences_changed` means the sender is preparing again; it carries no provider,
source or quality details and does not alter the room timeline.

Join/reconnect receives the current snapshot, resolves independently and starts at
the canonical position/play state. Browser autoplay restrictions can still require
a local user gesture. Source failure is local and leaves the room unchanged;
retry is explicit. There is no all-participants-ready barrier: the host decides
when to play.

`next_episode` uses the existing cached lifecycle, including season boundaries and
known air dates. If metadata is missing or the series ended it returns a normalized
unavailable error. The ordinary detail/player lifecycle enrichment warms this
cache; WebSocket commands do not fetch TMDB. Both generic content and next-episode
transitions reset the room to paused/position zero and participant readiness to
false. Participants independently inherit their own last resolved content's
preferences and resolve the destination. No transition/preparation marks it watched.

Each client continues its existing profile-specific playback state/activity saves.
No join, ready, sync report or room command writes watch history. Existing activity
aggregation handles sampled viewing, seeks, completion and progression; room
messages cannot multiply those records. The debug player saves its own progress
before changing content. On movie/episode completion each client records its own
completion; the host pauses the shared timeline. Room next episode is an explicit
host action in v1; solo autoplay is suppressed while attached to a room.

## Minimal verification UI

The existing playback page has a Watch Together panel: create/join by ID,
participants/readiness, host play/pause/seek-to-current-position, next episode,
reconnect/retry source, leave/close and drift/rate diagnostics. Native host player
controls also publish intent. Controls applied by synchronization are suppressed
from echoing back. The shared timeline owns autoplay while attached; the ordinary
player is otherwise unchanged. There is no final overlay redesign.

## Verification and smoke fixture

`tests/test_watch_together.py` covers lifecycle, authority/revisions, timeline,
drift, reconnect/stale cleanup/host grace, bounds, movie/episode identities, season
transitions, private source independence/failure, history isolation and payload /
cookie / Origin / revocation boundaries. Existing full-suite activity and playback
tests continue to exercise meaningful aggregation and delivery behavior.

`tests/manual/watch_together_app.py` is a guarded offline runtime fixture. It only
runs against `sqlite:////tmp/orbis-watch-smoke.db`, uses two mock providers and
cached seasons, and must never be a production entrypoint. The companion
`watch_together_smoke.py` drives **two separate cookie jars and WebSocket clients**
through nginx, checking independent sources, play/pause/seek, reconnect, episode
and season transitions, separate profile history, leave/close and absence of
transport secrets from room snapshots.

For the smoke run, backend and nginx shared only an isolated `--network none`
container namespace. The test nginx config changed the backend target to loopback;
Upgrade handling and built frontend assets were the production configuration.
No host ports, host routes, production DB or external providers were used.

Verification on 2026-09-24:

- Full backend suite: **168 tests passed** in one broad run (including existing
  playback/delivery/activity and fresh/legacy migration regression tests).
- Subsequent host-grace edge-case fix: expanded focused room suite **18 passed**.
- Frontend TypeScript and Vite production build passed. Existing React Router
  directive and Shaka bundle-size warnings remain non-fatal.
- Backend and frontend ARM64 production images built; aarch64 runtime, nginx
  configuration and real two-client HTTP/WebSocket smoke passed.
- `alembic check` reported no upgrade operations. Schema remains at
  `e64a0c31f952`; no new migration or production DB change is needed.
- `git diff --check` passed. No new runtime dependencies, Git/remotes operations
  or host networking/DNS/routing changes were made.
- No graphical browser or external/live provider playback test was run. The
  checked-in network smoke uses separate HTTP cookie jars and real WebSockets,
  not simulated media playback or a claim of cross-browser validation.

## Remaining hardening

- Rooms intentionally do not survive backend restart and cannot span multiple
  workers/replicas. A shared coordination store is only needed if deployment scope
  expands beyond the current single Raspberry Pi process.
- This is timeline coordination, not frame-accurate synchronization. Add measured
  RTT/clock-offset compensation and jitter/loss tests before promising tighter
  synchronization outside a local tailnet. Different source edits/cuts cannot be
  aligned automatically just from matching TMDB IDs.
- Two real browsers/devices should validate native autoplay permissions, actual
  media seeking/rate correction, background-tab throttling and source replacement.
  The network smoke test does not claim browser/media playback coverage.
- Soak-test slow/disconnecting clients and recovery under poor Wi-Fi. Decide the
  final UX policy for host buffering, all-ready barriers and automatic shared next
  episode before building the final player overlay.
- There is no chat, voting, guest accounts, subscription enforcement or shared
  media transport. Existing profile/session trust boundaries remain unchanged.
