# Watch Together: global room contract

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

A room contains a 192-bit opaque ID, a separate cryptographically random six-digit
join code, creator participant ID (retained for compatibility, not authority), optional canonical movie or TV
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
| Participant reconnect grace | 60 seconds after disconnection, for everyone |
| Lobby heartbeat cadence | 20 seconds while no playable video is active |
| Silent-connection timeout | 60 seconds after last heartbeat/activity |
| Disconnected participant retention | 60 seconds after disconnection |
| Idle room / absolute room lifetime | 30 minutes / 6 hours |
| Closed room retention | 60 seconds |
| Cleanup cadence | 5 seconds, plus request-time cleanup |
| Incoming JSON / outgoing queue | 4096 bytes / 16 messages per connection |
| Event rate | 10/second with a burst of 20 |

A disconnect retains the same membership for 60 seconds, including on reload.
Every participant may control playback and content. An explicit Leave removes only
that participant; the room closes when the last member leaves or expires. A
delayed old socket cannot mark its replacement disconnected.
The lifespan janitor also expires abandoned rooms when no further requests arrive.
Browser shutdown notifications are best effort, so an abnormal browser/OS kill
may take up to the grace period after the last heartbeat to close the room. A full
page reload retains the room handle in tab-scoped session storage and reconnects
without issuing Leave. Normal in-app navigation also retains membership.

## HTTP contract

All HTTP operations require the existing HTTP-only `playback_client` cookie and
`X-Orbis-Session` header. Profile/session validation is reused from basic sessions.
Responses are `Cache-Control: no-store`.

| Endpoint | Body / result |
| --- | --- |
| `POST /api/watch-together/rooms` | `{}` creates a content-less lobby; optional `{content, position}` preserves player-entry compatibility. Returns `join_code`, opaque room snapshot and own `participant_id`. |
| `POST /api/watch-together/join` | `{join_code:"482731"}`; generic invalid/expired response; per-session and per-source failed-attempt throttles. |
| `POST /api/watch-together/rooms/{id}/join` | Idempotent for an existing member/session; returns snapshot and own participant ID. |
| `GET /api/watch-together/rooms/{id}` | Member-only current snapshot. |
| `POST /api/watch-together/rooms/{id}/transition` | Member-only `{revision, content, position?}`; applies the same canonical content event/revision path as WebSocket control. |
| `POST /api/watch-together/rooms/{id}/exit` | Removes only the calling participant; last participant removal closes the room. |
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
  compatibility `host_id`, canonical content, projected `position`, `state`, `rate`, server time,
  lifecycle timestamps/status and participants/readiness. Join, connect, leave,
  ready, playback changes and close are broadcast as snapshots.
- `sync`: private correction advice for the reporting participant; never broadcast
  as another playback command.
- `error`: stable code such as `stale_revision`, `invalid_event` or
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

Supported types are `heartbeat`, `ready`, `play`, `pause`, `seek`, `position`, `content`,
`next_episode`, `preferences_changed`, `leave`. Any joined participant may submit
play/pause/seek/content commands; the server sequences them. `content` requires a canonical `content` object. `seek`/`position` require
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
snapshots as state, not replay them as commands. nginx forwards WebSocket
Upgrade/Connection and the original Host including port, so origin validation
works on LAN/Tailscale HTTP as well as HTTPS.

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
capability checks and adaptive broker. A participant can use one source and quality while
another uses a different source and quality; readiness and intent are the only shared coordination.
`preferences_changed` means the sender is preparing again; it carries no provider,
source or quality details and does not alter the room timeline.

Join/reconnect receives the current snapshot, resolves independently and starts at
the canonical position/play state. Browser autoplay restrictions can still require
a local user gesture. Source failure is local and leaves the room unchanged;
retry is explicit. There is no all-participants-ready barrier; any participant
may resume the shared timeline.

`next_episode` uses the existing cached lifecycle, including season boundaries and
known air dates. If metadata is missing or the series ended it returns a normalized
unavailable error. The ordinary detail/player lifecycle enrichment warms this
cache; WebSocket commands do not fetch TMDB. A generic content transition may
include the initiating participant's resume position; next episode starts at zero. Both transitions
pause the room and reset participant readiness. Participants independently inherit their own last resolved content's
preferences and resolve the destination. No transition/preparation marks it watched.

Each client continues its existing profile-specific playback state/activity saves.
No join, ready, sync report or room command writes watch history. Existing activity
aggregation handles sampled viewing, seeks, completion and progression; room
messages cannot multiply those records. The player saves its own progress
before changing content. On movie/episode completion each client records its own
completion; any participant may pause or initiate a shared next-episode transition.
The participant's local source/quality preferences remain private.

## Global frontend lifecycle

One root-level React provider owns the room socket across browse/detail/player routes.
The header exposes create/join, six-digit code, copyable invite URL, participants,
connection status and Leave. An invite `/?join=482731` waits for profile
selection, then opens the join panel. Ordinary browsing never publishes a
content event. Detail Play/Resume/Start Over and episode changes by any participant publish a
canonical transition. Other participants enter their own `/watch/{profile}/...` route and
resolves playback independently. The existing player menu consumes the same room
state, and leaving `/watch` keeps the room active. Profile switching explicitly
leaves the room. A reload retains the tab-scoped membership handle and reconnects
within the shared 60-second grace; browser/tab closure expires after that grace.
No long internal room ID is shown in the consumer UI.
The global client also checks room membership every 15 seconds while joined. A
closed room can temporarily return HTTP 200 with `status: closed` before its
retention window ends; the client clears its active-room indicator for that state
as well as for missing/expired-room responses.

## V1 limitations and targeted verification

The room is process-local; backend restart loses it. One Uvicorn worker is
required. Browser autoplay may require a local gesture; the client first tries
normal playback and offers an explicit audio-enable action when a muted fallback
is necessary. A source-resolution failure affects that participant, not the
canonical room or others. Timeline synchronization is approximate rather than
frame accurate, especially if independently resolved sources have different
edits. No chat, voice, account enforcement or persistent rooms are included.

Targeted automated room tests cover peer commands, stale revisions, 60-second
reconnection and room expiry. The release-candidate browser smoke must confirm
actual video readiness and advancing `currentTime` on two clients, not merely
matching navigation paths.
