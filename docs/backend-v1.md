# Orbis Backend V1

Contract status: **V1 FROZEN — 2026-09-24** (trusted personal/family deployment). This page is the entry point for final
frontend development. The contracts below describe its
practical limits. No `/api/v1` alias has been introduced:
existing `/api` paths are the V1 contract; the service/OpenAPI version is `1.0.0`.

## Contract references

- [HTTP OpenAPI snapshot](openapi-v1.json), also served at `/openapi.json`.
  The JSON lists every HTTP operation, typed request and existing response model.
  Some historical dictionary responses are intentionally described in the domain
  documents below rather than retrofitted with breaking envelopes.
- [Profiles, owner bootstrap, activity and library](profile-activity-foundation.md)
- [Canonical catalog, localization, search and IMDb](rich-catalog-search.md)
- [Recommendations and shelf feeds](hybrid-recommendations-feeds.md)
- [Provider / Source / Quality choices](playback-choices.md)
- [Adaptive delivery / relay](playback-delivery.md)
- [Episodes, capabilities and client sessions](episode-lifecycle-client-sessions.md)
- [Watch Together HTTP and WebSocket protocol](watch-together.md)
- [Backup, restore and deployment](v1-operations.md)
- [Public-release readiness notes](v1-public-release.md)

## Architecture and authority

The catalog owns canonical TMDB identity. Localized metadata supplies display
text. Activity aggregates meaningful viewing independently of mutable resume
state. Recommendations consume canonical features and profile signals; feeds
materialize bounded shelves. Playback resolves Provider → Source → Quality and
uses the delivery broker for attested resources. Client sessions track presence,
not history. Watch Together coordinates canonical intent, not media transport.

Profiles are household personas, not authentication accounts. Profile selection,
profile IDs and client names never confer owner authority. Owner-only HTTP
operations require `Authorization: Bearer <owner token>` from setup/login.
Owner sessions last eight hours; selecting a viewer in the verification frontend
logs out owner authority. Client sessions use `X-Orbis-Session` plus the
HttpOnly/SameSite=Strict `playback_client` cookie. The final frontend must create
its own session and send both on playback and room operations. Room WebSockets
authenticate in their first message, never a query-string token.

Ordinary catalog/profile/library use is trusted-household access, including
switching profiles. There is deliberately no viewer credential or per-profile
privacy boundary. All administrative provider operations, profile deletion,
episode-marker editing, admin sessions, delivery diagnostics, recommendation
and signal diagnostics require owner authentication. The owner cannot be deleted.

## HTTP map

Prefixes in braces below are literal path parameters, not alternative APIs.
`P = /api/playback/profiles/{profile_id}` and
`L = /api/library/profiles/{profile_id}`.

| Domain | Canonical operations | Authority / response |
| --- | --- | --- |
| Health/version | `GET /api/health` | Public status, `version`, `api_version` |
| Setup | `GET /api/setup`, `PUT /api/setup/locale`, `POST /api/setup/owner` | First-run locale/bootstrap only; closed once owner exists |
| Owner | `POST /api/setup/login`, `GET /api/setup/session`, `POST /api/setup/logout` | Credential issuance, validation, revocation; login lockout |
| Profiles | `GET, POST /api/profiles`; `GET, PATCH, DELETE /api/profiles/{profile_id}`; `POST /api/profiles/{profile_id}/self-delete` | List/object; DELETE remains owner-only; self-delete requires matching `X-Profile-Id` and exact `confirm_name`, returns 204; owner cannot be deleted |

| Search | `GET /api/catalog/unified-search` | `query`, `kind`, `limit`, `cursor`, optional `online`; results/groups/next_cursor |
| Catalog browsing / My List browsing | `GET /api/catalog/items` | `kind`, `profile_id`, `my_list`, `limit`, `cursor`; results/next_cursor |
| Genre browsing (additive V1 extension) | `GET /api/catalog/genres/{genre_id}/items` | Canonical TMDB genre ID; `kind=all,movie,tv`, `limit`, `cursor`; localized title, results, next_cursor |
| Genre search (additive V1 extension) | `GET /api/catalog/genres?query=&kind=` | Bilingual local genre matches with canonical ID, localized title and all/movie/tv scope; only genres represented in the cached catalog |
| Rich details | `GET /api/catalog/movie/{tmdb_id}`, `/tv/{tmdb_id}`, `/tv/{tmdb_id}/season/{season_number}` | Canonical identity + localized detail object |
| Credits | `GET /api/catalog/person/{tmdb_id}/credits`, `/company/{tmdb_id}/credits` | Cursor results with role context |
| Ratings | `GET /api/catalog/{kind}/{tmdb_id}/ratings` | Source/provenance-aware optional ratings |
| Trending | `GET /api/catalog/trending` | Existing TMDB discovery page; not personalized feeds |
| Feeds | `GET /api/feeds/profiles/{profile_id}/{surface}` | `surface=home,movies,series`; snapshot_id, shelves, next_cursor, warnings |
| Resume library | `GET L/continue`, `POST L/continue/hide`, `POST L/restart` | Continue list / `{ok:true}`; hide does not delete history |
| Durable history | `GET L/history?limit=100&offset=0` | Array; limit 1–500, newest first, content-key tie break |
| Explicit intent | `GET, PUT L/my-list`, `PUT L/not-interested` | Existing list array / `{ok:true}`; no implicit save |
| Playback state | `GET P/states`; `GET, PUT P/{content}/state` | State objects; save only actual viewing, not preparation |
| Playback resolution | `POST P/{content}/resolve`, `/choices`, `/refresh`, `/failover`, `/recover` | PlaybackSession; logical choices, capability outcomes, own delivery session |
| Episode lifecycle | `GET P/{episode}/lifecycle`; `POST .../prepare-next`, `.../transition` | Up Next/previous/season/end status, or privately resolved session |
| Client presence | `POST /api/sessions`; `GET, PATCH, DELETE /api/sessions/{session_id}` | Own cookie-bound session; heartbeat is not watch evidence |
| Media transport | `GET, HEAD /api/playback/sources/{session_id}[/{resource_id}]` | Opaque bearer capability, media bytes/manifest; never client URL or headers |
| Watch Together | `POST /api/watch-together/rooms`; `GET /rooms/{room_id}`, `POST /rooms/{room_id}/join`, `/resolve` under same prefix | Existing client session + membership; resolve response private to caller |
| Provider manager | `/api/admin/providers` list, `/{provider_id}` PATCH, `/test`, `/logs`, `/resolve-test/...`, `/discovery-errors` | Owner only; see OpenAPI for all movie/TV diagnostic variants |
| Provider editor | `/api/admin/provider-editor` create/list; `/{provider_id}` inspect/delete; `/override`, `/draft`, `/validate`, `/activate`, `/rollback/{version}`, `/revert-to-factory`, `/settings`, `/reload` | Owner only; trusted Python code and intentional owner-only settings access |
| Session/marker administration | `/api/admin/sessions`, `/api/admin/episode-markers/tv/...` | Owner only |
| Diagnostics | `/api/admin/system`, `/api/admin/watch-together/rooms`, `/api/admin/playback/delivery`, `/api/feeds/profiles/{profile_id}/diagnostics/{snapshot_id}`, `L/signals` | Owner only, safe structured state |

Viewer profiles are selectable local profiles, not authenticated accounts. The self-delete confirmation protects against accidental deletion; `X-Profile-Id` is selection context, not a security credential. Deletion removes that profile's playback, history, list and preferences through database cascades, revokes its delivery sessions and removes it from active Watch Together rooms. The installation owner remains protected server-side.

Playback `{content}` is `movie/{tmdb_id}` or
`tv/{tmdb_id}/season/{season_number}/episode/{episode_number}`. `{episode}` is the
latter only. Admin provider resolve tests retain historical `season`/`episode`
parameter names; the wire path shape and canonical identity are unchanged.

## Identity, localization and pagination

- Canonical media type is `movie` or `tv`. `series` is a surface/UI concept.
  Title keys are `movie:ID` / `tv:ID`; episode keys add `:sN:eN`. Search entity
  kinds additionally include `person` and `company`. IDs never include locale.
- Catalog accepts `profile_id` as query context for preferred locale. Playback,
  library and feeds put it in their paths. Session creation puts it in the body;
  room operations derive it from the validated session. Do not infer authority
  from any of these representations.
- `en-US` and `tr-TR` records coexist. Profile locale controls display, not search
  discoverability or recommendation identity. English fallback is permitted.
  Existing shelf titles and provider messages are display text; render by `kind`,
  `context_key` and stable codes, never parse translated titles for behavior.
- Search/catalog limit is 1–50, default 20. Genre browsing defaults to 24.
  Feed batch_size is 1–5, default 3, with up to six items per normal shelf.
  Home mixes
  movies/TV; Movies and Series enforce their media scopes.
- Treat cursors as opaque. Keep query/profile/locale/filter/page-size scope
  unchanged across continuation. A replay returns the cached page while valid.
  `next_cursor:null` means exhausted for catalog/genre queries; a main discovery
  feed with viable semantic templates continues through controlled recycling.
  Never manufacture offsets from cursor text.
- Catalog uses a creation-time ceiling and keyset order; mixed-genre queries
  order by canonical TMDB ID so the first page can contain both media types.
  Search uses bounded candidates and cached remote continuation. Feed cursors
  reference a bounded candidate/template snapshot plus generation and recency
  state. Cursor reads do not repeatedly warm TMDB.
- HTTP 409 `feed_invalidated` means meaningful profile signals changed: restart
  the feed. HTTP 410 means TTL/capacity expiration: restart the query/feed. HTTP
  422 `cursor_scope_mismatch` means the supplied cursor belongs to another scope.
- Search/feed cache has a shared hard cap of 2048 rows; pressure may expire a
  cursor early. No frontend may assume a cursor is durable storage.

## Errors and compatibility

HTTP errors now add `error` while preserving the old `detail` field:

```json
{"detail":"Profile not found","error":{"code":"profile_not_found","message":"Profile not found","details":null}}
```

Use `error.code` and status for logic. `message` is a safe human-readable fallback,
not an i18n key. `details` may contain validation locations/types or domain outcome
information; request input and exception context are excluded. Validation is 422,
authentication 401, authorization 403, unknown/scoped resources 404, conflicting
state/compatibility 409, expiry 410, rate limits 429, unavailable upstream 502/503.
Unknown server failures are generic 500 without exception text. See
`core/errors.py` for exact named codes; generic status codes are stable fallbacks.
WebSocket errors retain `{type:"error",code,revision?}`; HTTP envelopes do not
wrap room events or media bytes.

Deprecated but retained, marked in OpenAPI:

- `/api/catalog/search`: old remote-only `CatalogPage` search. Use unified-search.
- `/api/admin/provider-editor/discovery-errors`: duplicate of the canonical
  `/api/admin/providers/discovery-errors` operation.

No endpoint was removed and no success envelope was globally rewritten. Existing
`L/my-list` remains the compatibility array; use cursor-based `/catalog/items`
for the final browsing UI. `P/states` is resume state, not history or a feed.
HEAD relay requests remain supported but share GET semantics and are omitted
from generated OpenAPI to avoid duplicate operation IDs.

V1 additions are the normalized error envelope, version fields, owner diagnostics
and explicit deprecation annotations. Security tightening is intentional:
previous anonymous delivery/signal/recommendation diagnostics now return 401.
Future compatible optional fields and security fixes are allowed; structural
renames/removals or changed identity semantics require a new contract version.

## Post-freeze provider settings security correction

V1 remains frozen. A prior security correction to provider Settings is
documented in the [provider-authoring guide](provider-authoring.md): owner-only GET/PUT at the
existing `provider-editor/{id}/settings` paths now return
`{schema, values, configured_secrets, schema_available}`. Secret values are omitted,
never returned in plaintext. PUT retains `{settings:{...}}`, merges supplied
**declared** keys, preserves omitted values and uses null to clear/reset. Validation
and schema metadata support the small generic form. The prior raw JSON response
could expose stored secrets and could not drive a declared-settings UI; retaining
that behavior was unsafe. Update any private raw-settings client to this masked
view. The bundled verification admin UI and OpenAPI were updated together.

`MediaProvider.settings_schema` is optional and defaults empty; runtime values are
accessed server-side using `providers.settings.runtime_settings`. Code rollback
preserves configuration and sensitive-key classification. See
[provider authoring](provider-authoring.md) for fields and lifecycle. No other
frozen success shape/path, identity, catalog/feed/recommendation or playback
contract changed. Production discovery no longer imports bundled mock adapters;
the reference is opt-in, while this private build retains the existing real adapter
pending the documented migration before public release.
