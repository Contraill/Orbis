# Orbis playback choices and factory overrides

## Normalized choices

The hierarchy is provider → stable adapter-local source/host → quality.
`PlaybackSource.source_id` is an optional stable slug such as a host/player name,
not an embed ID, URL, hostname inferred by core, or Shaka variant ID.
Adapters that do not supply a stable key still work in Auto mode.

Preferences are nullable (`null` means Auto), stored per profile/canonical content:
`preferred_provider_id`, `preferred_source_provider_id`, `preferred_source_id`,
and `preferred_quality_height`. A source preference always has a provider scope.
No resolved URL, headers, session token, or player track ID is stored in SQLite.
Old clients saving progress without these fields do not clear them.

The server prefers the explicit provider, otherwise the last provider and normal
priority/health/circuit policy. An unavailable preference is a soft preference:
playback falls back without erasing it. Source preference precedes ordinary
source ranking; otherwise equivalent sources avoid required relay where possible.
Expired sources are never selectable. A source failure first uses adaptive
delivery recovery, then untried sources from that provider, then another provider.
Consumed source candidates and failed-provider exclusions stay session-scoped.
Expiry refresh re-resolves, retaining logical preferences and progress.

Responses include `choices.providers`, `choices.sources`, `choices.qualities`,
and `choices.selected_quality_height`. Provider entries represent enabled,
capable providers, not a promise that every provider carries the current title.
Source entries represent resolved, usable sources only. HLS qualities come from
actual master `EXT-X-STREAM-INF` resolutions. Encoded widths and heights are
classified into consumer tiers (for example 1920×816 is 1080p); variants in the
same tier appear once while raw dimensions remain in `encoded_variants`. Discovery
uses the safe upstream fetcher with a five-second budget and bounded manifests;
failure leaves Auto available, never invents resolutions or blocks playback.
Explicit quality uses the requested height, the nearest available lower height,
or the smallest available height if all exceed the request. Unknown qualities
fall back to Auto. Non-HLS quality-labelled sources use the same logical policy.

`POST .../choices` accepts the existing transition snapshot and a scoped server
source-session ID. Quality-only changes reuse the delivery session and master;
the isolated player applies the server's height as an ABR restriction, allowing
audio/codec variants at that height. Shaka IDs never leave the player abstraction.
The UI shows both the preference and current source/applied quality. Provider
audio `track_id` is provider metadata, never a Shaka rendition ID. The player
matches actual manifest renditions by language, original/dub intent, labels,
roles and available Shaka group metadata, then checks the active Shaka track
after selection. If no requested rendition is active, the UI reports the
actual track or a concise fallback state instead of claiming success.

## Explicit cross-origin interoperability

`DeliveryHints.resource_origins` is an exact-origin allowlist, bounded to 64.
`resource_headers` maps those exact origins to explicit non-secret header grants.
Only `User-Agent` and `Referer` are allowed; wildcard origins, paths, credentials,
CR/LF, arbitrary headers and unlisted targets are rejected. Each redirect is
revalidated and receives only its own grant. Cookie/Authorization remain confined
to the original source origin; they are never inherited across an origin change.
DNS pinning/private-address protection, registered resource ancestry, bounded
sessions, Range and streaming behavior remain in force. Clients cannot submit
upstream URLs or headers. Source metadata and these grants remain server-side.

For HLS media resources mislabeled as playlists/images, the relay checks bounded
container bytes (three aligned TS sync bytes or an ISO-BMFF box header) and fixes
only Content-Type. Bytes, Range offsets and lengths are unchanged. A HEAD/nonzero
Range request may need a bounded initial-byte probe; the detected MIME is kept
in the bounded source session. Unknown containers fail closed. No segment rewriting,
transcoding, sanitizer, DRM handling or ad filtering is performed.

Sources requiring these grants use the existing full relay path. Public sources
still start direct and escalate on evidence. This does not solve browser challenges,
authentication, DRM, access restrictions or paywalls.

## Factory + override

`POST /api/admin/provider-editor/{id}/override` creates an editable draft from the
shipped adapter and an explicit override marker under `/config/providers/{id}`.
It is idempotent and does not overwrite an existing draft or activate anything.
The normal save → validate → activate → versions → rollback lifecycle applies.
Only explicitly marked overrides may replace a factory provider with the same ID;
accidental duplicate IDs are still rejected. Existing provider state/priority is
keyed by that unchanged ID. Failed activation preserves the installed registry
and active file. On restart a malformed override falls back to the factory.

`POST .../{id}/revert-to-factory` archives the active override, removes only its
active file, and atomically installs the shipped provider under the registry lock.
Failure restores the active file; drafts, settings and versions are retained.
No Docker restart or image rebuild is needed for the override lifecycle. Existing
playback sessions may finish with their already-resolved sources.

The admin Providers page offers a confirmed Delete action for user-created live
providers, including inactive drafts. `DELETE /api/admin/provider-editor/{id}`
removes that adapter's code, settings and versions, unloads it without a restart,
and clears its registry state. Historical provider events and logical playback
preferences are retained. Factory providers and factory overrides cannot be
deleted through this route; use Revert to Factory for an active override.

This is a trusted administrator code editor, not a Python security sandbox. It
retains the existing deployment's admin access boundary. Do not expose it publicly.

## Validation boundary

The public fixture tests provider/source fallback, manifest quality classes,
header grants and recovery without relying on a real third-party service.
Installation-specific provider observations are kept in private operator notes,
not in the public authoring guide or release artifact.
