# Profile, installation and activity contracts

## Installation and owner authority

A fresh migrated database contains an installation row, **zero profiles**, and
no default password. The first-run screen initially uses English and saves an
explicit `en-US` or `tr-TR` installation locale using `PUT /api/setup/locale`.
`POST /api/setup/owner` creates the first profile, stores a salted scrypt password
hash, closes setup and issues an admin session in one SQLite write transaction.
Concurrent claims cannot create a second owner. The owner profile inherits the
installation locale unless an explicit profile locale is supplied. A partial
unique index permits only one owner; the installation reference prevents its
deletion. Setup never reopens after ordinary profile deletion.

This is a household application: viewer profiles are identities/preferences, not
separate password-protected user accounts. Household clients can select profiles
and access their playback/library/preferences. This does **not** authorize admin
operations. After bootstrap, profile creation needs no owner password; new profiles
are always viewers. Profile deletion and every `/api/admin/*` operation require
an owner bearer session. Profile payloads reject role/credential fields. Selecting
the owner profile alone grants nothing. The UI drops/revokes admin credentials
when switching away. Credentials are never put in URLs or profile responses.

Owner sessions expire after eight hours; only SHA-256 token digests are stored,
and the session table is bounded to ten live sessions. Browser tokens are held
in sessionStorage, not persistent localStorage. Logout and local password reset
revoke sessions. Five failed password attempts impose a five-minute installation
lockout. Cross-origin API access is not enabled. Use trusted HTTPS when credentials
cross an untrusted network; this milestone does not configure TLS or host networking.
The initial setup is a first-claim operation: keep a new installation accessible
only to its intended owner until setup completes. This is not Internet-facing
multi-user authentication or a sandbox for provider code.

### Existing installation migration / credential recovery

Migration `b91f02a7c640` preserves all profiles and playback rows. The smallest
existing profile ID becomes owner deterministically; all others remain viewers.
Locale starts at `en-US`, avatar seeds are copied once from existing names, and
new preference defaults are applied. No historic watch duration is invented from
resume positions. Existing resume entries remain eligible under the legacy resume
policy; new evidence is collected only during later viewing.

Existing installations have **no owner password until set from the local console**:

```sh
docker compose exec backend python -m core.owner
```

The command prompts twice without echo, requires 12–128 characters, updates the
owner credential and revokes all admin sessions. It does not accept a password
in command arguments or print it. It also serves as local-console recovery.
There is deliberately no unauthenticated remote “claim existing owner” endpoint.
Provider configuration and ordinary playback continue to work while admin access
is locked. Live provider editing/execution administration requires owner login.

## Profiles and localized metadata

Profiles expose name, independent `avatar_seed`, locale, preferred audio/subtitle
languages, subtitle default, autoplay-next and trailer-muted flags, plus zero to
five unique `{media_type: movie|tv, tmdb_id}` onboarding selections. Selection is
optional and may be completed later. Renaming does not alter the stored avatar
seed. `Blobatar` renders SVG locally from the stable profile seed and optional validated avatar configuration; Orbis centrally controls palette and
variant. No external avatar API is contacted.

The active profile determines UI locale and catalog `profile_id` requests.
`localized_metadata` is keyed by `(canonical content_key, locale)` and retains
localized title/overview/genres plus the original title. Movie/series identity
does not change with language; season representations have their own canonical
keys. Detail and list fields merge within a locale, never across locales.
Both `en-US` and `tr-TR` can coexist. Library responses use the requested profile's
cached locale, then cached English, then identity-only placeholders. Full
cross-language title search/indexing is a later milestone; current search still
uses TMDB, and storage preserves the titles that future indexing needs.

Audio/subtitle defaults are applied when first resolving content without a saved
playback state. Existing content preferences remain authoritative. Autoplay uses
the backend's known next-episode target; it never guesses episode numbers.
Trailer mute is persisted for a later trailer integration.

### Adding another profile

After setup, **Add Profile / Profil Ekle** is visible next to the existing profile
cards on the selection screen and at the top of Profile preferences. Both links
open `/profiles/new`. The creation form is available without owner sign-in after
first-run setup has closed. Before bootstrap, `POST /api/profiles` returns 409.

Creation and editing share the same preferences/onboarding fields: name, previewed
avatar seed, locale, audio/subtitle defaults, autoplay-next, trailer mute and up to
five selections. A new avatar defaults to the entered name unless customized.
Creation uses the existing `POST /api/profiles` contract and selects the new viewer
profile after success; it never calls bootstrap or grants an owner role.
Viewer selection hides the Admin link and drops the owner session. Selecting the
owner restores the Admin link, but actual admin access still requires authentication.

## Viewing evidence versus resume

`playback_states` remains mutable resume/preferences state. `viewing_progress`
holds durable per-profile, canonical movie/episode evidence: first start, last
watch, accumulated duration, completion and rewatch counts. `viewing_days` holds
at most one aggregate per profile/content/UTC day, including visit counts and
completions. Periodic saves update these aggregates, not an append-only event log.

Only positive position deltas consistent with elapsed server time count. Up to
2× playback is supported; seeks and gaps over two minutes receive no duration
credit. The first sample establishes a baseline. Zero-position/idle preference
saves do not create history. Sixty accumulated seconds makes viewing meaningful.
A completion signal requires a known duration, reaching the end, and at least
80% of the duration actually accumulated (minimum 60 seconds). A client completion
flag or seek alone therefore cannot create positive completion evidence.
Very short clips may never qualify; telemetry is conservative and is not proof
that a person paid attention. Concurrent saves serialize resume/evidence updates.

Start Over / Play Again reset only the current playback cycle and resume position.
Earlier history is retained. A rewatch signal is counted after a previously
completed item accumulates another meaningful cycle, not on clicking Play Again.
UTC-day aggregates and meaningful episode counts preserve weekly progression;
return visits are separated by at least 30 minutes.

## Library API

All routes below are under `/api/library/profiles/{profile_id}`:

- `GET /history?limit=100&offset=0`: durable movie/episode evidence, including weak
  starts clearly distinguished from meaningful viewing.
- `GET /continue?kind=all|movie|tv`: resumable movies and **one card per series**.
  The latest meaningful episode wins. Completed movies are excluded; a completed
  episode may point to the next known aired episode from cached season metadata.
  No next target is fabricated if metadata is absent. Older installations' resume
  rows are preserved without backfilling speculative behavioral history. A saved
  meaningful resume position remains eligible even when the first new activity
  sample is short; this does not make it a positive recommendation signal.
- `POST /continue/hide`: movie/series identity only. Stores an independent
  suppression marker and watched-duration baseline. At least 60 seconds of new
  actual viewing in that movie/series makes it eligible again. History remains.
- `POST /restart`: canonical movie/episode identity. Clears resume/completion for
  the current cycle without deleting history, My List or delivery preferences.
- `GET /my-list?kind=all|movie|tv` and `PUT /my-list` with identity and `enabled`:
  explicit membership only, ordered by addition timestamp. Idempotent re-add does
  not reorder; removing and later adding gets a new timestamp. Watching never adds.
- `PUT /not-interested`: identity and `enabled`, independent negative feedback.
- `GET /signals`: provider-independent recommendation feature boundary. Exposes
  onboarding intent, My List, negative feedback, actual watched duration,
  meaningful episode counts, completions, rewatches, active UTC days, return visits,
  recency, sustained series progression (two meaningful episodes on two days), and
  stale incomplete starts (30 days). A start alone is not affinity. No recommendation
  ranking or “liked because watched” inference is implemented.

The minimal profile/library pages exercise these APIs. New setup/profile/library
controls are bilingual; legacy technical admin/player diagnostics remain mostly
English pending the final frontend localization pass. No final UI redesign is
included. History UI shows the latest 100 entries; the API supports pagination.

## Verification

Final verification for this increment is reported with the milestone handoff.
No schema change or new migration was needed for the profile creation, provider
deletion, or Continue Watching eligibility corrections.

`tests/browser_fixture.py` provides a guarded, isolated `/tmp` database and mocked
TMDB for `app/frontend/tests/profile-foundation.mjs`. The Chromium check redirects
API traffic only to that fixture and exercised first setup, Turkish/English
switching, five selections, avatars/rename, preference editing, series dedupe,
Continue suppression/history retention, My List filters/removal, viewer denial
and password-authenticated owner re-entry. It does not modify live user data.
Playwright/Chromium are temporary test tools, not application dependencies.
