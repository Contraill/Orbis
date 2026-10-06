# Provider authoring (Orbis Backend V1)

Providers translate canonical TMDB IDs into independently playable sources. The
public authoring reference is `providers/adapters/reference/provider.py`. It uses
synthetic fixtures, not a third-party streaming website. The framework, this
example and its tests suffice to author a provider without reading private adapters.

## Module and installation

Export one `PROVIDER` instance of `providers.contract.MediaProvider` from a Python
module. Use a stable lower-case ID matching `[a-z0-9][a-z0-9_-]{1,63}`. Implement:

```python
class ExampleProvider(MediaProvider):
    id = "my-provider"
    name = "My provider"
    default_enabled = False
    default_priority = 100
    capabilities = ProviderCapabilities(movie=True, episode=True, protocols=["hls"])
    settings_schema = ()

    async def health_check(self): ...
    async def search(self, query): ...
    async def resolve_movie(self, tmdb_id): ...
    async def resolve_episode(self, tmdb_id, season, episode): ...

PROVIDER = ExampleProvider()
```

Return `ProviderHealthResult`, a list of `ProviderSearchResult`, or a list of
`PlaybackSource`, respectively. Async methods must bound network time/response
size, avoid blocking CPU work and close responses. Imports must not perform
network requests or other activation side effects. Capability declarations are
validated Pydantic data; declare only what the adapter supports. Search results
carry adapter-local external IDs, while playback resolution receives canonical
TMDB identity. Never create a second catalog identity from translated titles.

For a user-installed provider, use the existing admin provider editor:

1. Create a unique ID/name (creates `/config/providers/<id>/draft.py`).
2. Paste/upload the self-contained module into the draft. Validate it.
3. Activate; successful activation installs `active.py`, and the registry reloads.
4. Configure declared settings and enable the provider in the provider manager.
5. Test health/resolution before using it with a real profile.

In the standard Compose deployment `/config` is the host `config/` directory.
Package/distribute a source module plus README/tests, not somebody's live directory,
settings, versions, tokens or resolved URLs. Reuse the installed Orbis contracts;
do not add your package to the core factory directory to install it locally.
For a previously shipped adapter moved to private runtime, preserve its exact
provider ID and place its validated active implementation at
`config/providers/<id>/active.py`. Keep drafts, versions and `settings.json` in
that same ignored directory. Remove an obsolete `factory-override` marker only
after the private active implementation works without a factory module; that
turns it into a normal user/live provider without changing saved preferences.
Third-party Python dependencies are not dynamically installed by the editor. V1
providers should use the shipped standard library/httpx/contracts or document a
separately reviewed custom image. There is no second plugin installer.

## Provider → Source → Quality

The provider ID identifies an adapter; `source_id` identifies a stable logical
player/source within that adapter (`primary`, `backup` in the example). Human
labels are separate from IDs. An embed ID, signed URL, session token or Shaka
variant ID is never a persistent source ID. Quality is a normalized height/label,
usually discovered from HLS master variants; do not model every resolution as a
separate provider. HTTP single-quality sources can declare `quality="360p"`.
HLS master dimensions are normalized into consumer classes using both encoded
width and height: a cropped 1920×816 rendition is still 1080p. Multiple encoded
variants of one class appear once; raw dimensions remain in the choice contract.
Do not report a provider audio `track_id` as a Shaka rendition ID. Provider IDs
are stable adapter metadata; the player matches manifest audio by language,
original/dub intent, label and roles, then confirms the active rendition.

Return multiple independently usable sources when available. Their protocol,
codec/HDR information (only if known), audio/subtitle tracks, expiry and optional
delivery hints remain per source. Client capability filtering and normal
Provider/Source/Quality fallback are core responsibilities. A failed source must
not discard another resolved source. Raise `ProviderUnavailable` with a safe,
non-secret explanation if none are usable; unsupported media should fail clearly.
Do not claim success with an empty or invented media URL. Health and circuit
state are separate from configuration settings.

## Headers, origins and security

Only return adapter-resolved URLs/headers. Supply required server-side headers on
`PlaybackSource.headers`; they cause protected broker delivery rather than being
sent to the browser. Declare additional resource origins/headers only when the
adapter has established their ancestry and role; see `DeliveryHints` and
[delivery contract](playback-delivery.md). Source credentials are not implicitly
forwarded to unrelated origins. URLs/tokens expire; expose `expires_at` when known
and resolve fresh on expiry. Never put credentials in names, IDs, errors or logs.

The relay's public-address validation, DNS pinning, redirect and resource-ancestry
checks remain mandatory. Client-supplied URLs/headers are not a provider API.
Private-address relay is not enabled by using a local authoring fixture. Trusted
owner Python runs with container authority; validation has resource limits but is
not a sandbox. The framework cannot prevent deliberately malicious provider code
from reading files, making requests or printing secrets. Activate trusted code only.

## Declared configuration

Use `providers.settings.Setting` and `runtime_settings(self)`:

```python
settings_schema = (
    Setting(key="label", label="Source label", type="string", default="Example", max_length=40),
    Setting(key="enabled_backup", label="Use backup", type="boolean", default=True),
    Setting(key="timeout", label="Timeout seconds", type="integer", default=5, minimum=1, maximum=15),
    Setting(key="mode", label="Mode", type="enum", choices=["normal", "fallback"], default="normal"),
    Setting(key="endpoint", label="API endpoint", type="url", required=True,
            default="http://127.0.0.1:8765", allowed_hosts=["127.0.0.1"], allowed_schemes=["http"]),
    Setting(key="token", label="API token", type="secret", description="Stored server-side only"),
)
```

Fields support key, label, description, type, required/default, max_length,
integer minimum/maximum, enum choices and optional URL host/scheme constraints.
There are at most 32 uniquely keyed fields. Types are strict: a boolean is not
an integer. URL syntax rejects credentials/fragments; optional host constraints
are exact names, not wildcards. Providers still validate business-specific path,
query and networking rules. `sensitive=True` also marks another type sensitive;
secret defaults in code are forbidden. Never embed real credentials in defaults,
module source, fixture data or exception text.

`runtime_settings(self)` is a **server-side** helper returning validated current
stored values with declared defaults. It reads at operation time, so settings
changes need no activation. Do not import/read live values while declaring the
module/schema. Inactive drafts do not execute merely to discover settings: the UI
asks for validation/activation first. Zero-schema active providers display
**No configurable settings**. Do not invent options solely to populate a panel.

Settings live outside versioned source in `settings.json`, written atomically with
0600 permissions from creation. `settings-sensitive.json` retains sensitive key
classification independently of source versions; downgrade/rollback cannot
accidentally reveal an old secret as plain text. Back up the whole directory.
Unknown old settings are retained privately when a schema changes, but are not
returned by the public settings view. Validate required configuration again in
runtime operations because a new code version can add required fields.

Owner-only `GET/PUT /api/admin/provider-editor/{id}/settings` return:

```json
{"schema":[],"values":{},"configured_secrets":[],"schema_available":true}
```

`values` includes only non-sensitive fields. Secret values are **omitted**, not
replaced with a round-trippable placeholder. PUT still accepts `{"settings":{...}}`
but merges only supplied declared keys: omission keeps an existing value, `null`
clears/resets it, a supplied value replaces it. A required value without a default
cannot be cleared. PUT returns the same masked view, never the submitted secret.
Schema errors/invalid values use normalized HTTP errors without echoing input.

A schema/default belongs to source code; user values do not. Activation, rollback
and factory revert do not erase settings. Enabled state, priority, health,
version state, provider/source choice and quality remain separate core concepts.

## Lifecycle and deletion

Factory providers are shipped modules discovered under `providers/adapters/*`.
They can be enabled/disabled. Editing creates a private `factory-override` directory
with a copied draft; until activation the shipped implementation still runs.
Validation precedes activation; versions support rollback; revert-to-factory
removes the active override while retaining drafts, versions and configuration.
The shipped factory is never deletable through the admin API.

User/live providers can be enabled/disabled, edited, validated, activated, rolled
back or deleted. Delete requires explicit UI confirmation. The backend stages the
entire directory outside discovery, reloads the registry and removes the staged
code/drafts/versions/settings on success; reload failure restores it. The provider
state row is removed. Profile history is not deleted. Saved provider preferences
remain logical IDs and normal resolution skips an unavailable provider in favor
of remaining candidates; no remaining source means a normal resolution failure.
Existing issued delivery capabilities can finish/expire under the ordinary broker
policy; deletion is not a retroactive history purge or transport redesign.

## Reference walkthrough and fixtures

`reference` is a shipped **disabled-by-default authoring example**, not a usable
third-party media catalog. Its mapping JSON includes movie 157336 and TV 1396 S1E1/
S1E2 solely as known canonical IDs; all titles/media are synthetic test patterns,
not those copyrighted works. Never enable this fixture on a real family's profiles
and mistake generated video for the canonical title.

The adapter fetches at most 64KiB/20 records from a loopback fixture service with
a three-second HTTP timeout, no redirects and no environment proxies. Its URL
schema and runtime validation reject non-loopback metadata endpoints. The catalog
maps IDs to two stable sources: a primary HLS master (720p/360p) and backup 360p MP4.
Settings exercise text, integer TTL, boolean backup inclusion, enum failure scenario,
URL and an optional synthetic token. Source headers/expiry are demonstrated; the
`primary_unavailable` scenario preserves the backup, while disabling both fails.

Run in a disposable development environment sharing the backend's network namespace:

```sh
python tests/provider_fixtures/reference/serve.py 8765
```

To exercise required headers, start the fixture with `ORBIS_FIXTURE_TOKEN` set
to a synthetic value and configure the same value in `fixture_token`. The fixture
returns HTTP 403 when `X-Fixture-Token` is absent or incorrect. Do not use real
credentials for this example; request logging is disabled.

This serves the JSON and master playlist from local files. Optional actual media
can be generated locally (ffmpeg is a developer tool, **not** an Orbis dependency):

```sh
cd tests/provider_fixtures/reference
sh generate-media.sh
```

Returned media uses reserved `https://media.orbis.example/...` URLs. Automated
transports/browser routes map that origin to the local fixture resources; they do
not resolve an external service. This deliberate fixture origin does **not** work
as a real public CDN and is not a reason to permit loopback through production
relay. The existing manual Watch Together browser fixture shows actual-video
browser interception; use owned public HTTPS origins when building a production
adapter. Pure unit tests inject `httpx.MockTransport` instead of contacting a site.

`tests/test_provider_public_readiness.py` covers discovery, canonical mapping,
health, variants, fallback, schema validation, masking/clearing, version persistence
and deletion. `test_live_providers.py` uses the neutral factory for override/
activation/rollback/revert and failure restoration. Old mock adapters live only in
`tests/provider_fixtures`, excluded from production Docker images. The manual
provider browser smoke covers Settings and delete confirmation against an isolated
app plus the actual loopback fixture service.
The manual script `tests/manual/provider_readiness_browser.cjs` requires
`ORBIS_PROVIDER_FIXTURE=1` and a fresh disposable app/database/config: it bootstraps
an owner and exercises provider deletion. Never run it against the private installation.
