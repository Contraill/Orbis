# Playback resolution and delivery

Providers resolve content into `PlaybackSource`. Delivery is a separate decision
made by `playback.delivery.DeliveryBroker`. Adapters never construct application
URLs or select player/platform-specific paths.

## Resolution

`providers.resolution.resolution_broker` supplies an isolated HTTP/cookie session
per provider resolution attempt. Existing provider-manager timeouts, circuit
breakers and fallback ordering still apply. Transports are closed when an attempt
finishes or is cancelled.

- `auto`: server HTTP first; an HTTP 403 permits a browser-like HTTP retry.
- `server_http`: ordinary HTTP fetch with a request-scoped cookie jar.
- `browser_http`: browser-like headers and cookie sessions; no JavaScript execution
  or browser TLS impersonation is claimed.
- `real_browser`: an injectable transport factory; no browser process is installed
  in the application.
- `client_egress`: reserved capability, explicitly unavailable until a client-side
  resolution transport is supplied. There is no companion/native implementation.

The current adapter uses the browser-like HTTP session for its existing document
requests. Its catalog and extraction logic remain in the adapter.

## AUTO delivery

Public HTTP, HLS and DASH sources begin direct. Sources with required headers, or
trusted adapter metadata declaring resolution-egress affinity, require server
delivery. HLS and HTTP can use that path; DASH relay remains unsupported.

The player reports normalized network/media failures to the content-scoped
`recover` endpoint, along with its current position and preferences. It does not
send target URLs, request headers, relay modes or platform information.

For network failures the broker tests a server-attested resource of the failed
kind through server egress. It only escalates if that probe succeeds:

1. A manifest failure first relays the root, preserving direct variant URLs.
2. A further manifest failure relays child manifests, preserving direct media URLs.
3. A key, init or media failure enables relay for that resource kind and the
   manifests needed to address it. Media segments stay direct until media evidence
   requires their relay. Required source headers are an exception: they already
   prove direct browser fetches are insufficient.

Each escalation returns a new source session with the same logical source and
expiry. No provider re-resolution is needed. Expired sources use normal refresh;
unrecoverable delivery and codec failures use normal provider fallback. Playback
state still contains only logical content/user state, never stream URLs.

Compatibility observations are keyed by an opaque, HttpOnly browser cookie,
provider and source origin/path. They live for 15 minutes; subsequent escalations
do not extend that original deadline. Refresh uses those observations, and new
resolution after expiry retries direct. Existing streams are not interrupted just
to downgrade their delivery. Observations are not global claims about a provider
or host, and reset on process restart.

## Relay security and limits

The root URL comes from the trusted adapter. Child resource IDs are generated only
from fetched HLS manifests or adapter-supplied external subtitle metadata. The
client receives capability URLs, never an arbitrary URL-fetch endpoint. Query
parameters on relay endpoints are rejected. These opaque capabilities are bearer
access tokens, not a replacement for application authentication.

Resources must share the source origin or an explicit adapter-declared
`delivery.resource_origins` origin. Every fetch and redirect validates HTTP(S),
standard ports, public DNS results and origin membership. Connections use a
validated IP with the original Host/TLS hostname, preventing a second DNS lookup
from rebinding the target. HTTPS downgrades are rejected. Source credentials are
forwarded only to the source origin. Client cookies, Authorization, Referer and
arbitrary headers are never forwarded; only Range and If-Range are accepted.
Adapters may explicitly grant non-secret User-Agent/Referer headers to exact
allowlisted origins through `delivery.resource_headers`; grants are re-evaluated
on every redirect and never inherited. The origin list is bounded to 64.

Manifest bodies are capped at 1 MiB and rewritten using their final upstream URL
as the relative-URI base. Segment/key/init bodies stream with backpressure; they
are not buffered as whole media files. Nginx response buffering is disabled.
Range, content type, content length and content range are retained for resources.
An attested HLS media resource with an incorrect playlist/image Content-Type can
be normalized using bounded container-byte detection, without altering media bytes.
Rewritten manifests do not reuse upstream ETags or lengths.

Limits: 256 source sessions, 4096 resources per session, 32768 total resources,
eight levels of manifest ancestry, four fetch attempts including redirects, five
seconds for DNS and bounded network timeouts. Sessions last at most six hours;
expired sources cannot be relayed and have a ten-minute refresh grace. Repeated
recovery of the same session/resource kind is rejected.

`GET /api/admin/playback/delivery` exposes recent delivery plans and normalized
failure/probe evidence without signed URLs, credentials or complete session IDs.
Normal clients see generic errors; Shaka details remain in browser diagnostics.

## Boundaries

- HLS master/media playlists, relative URIs, alternate renditions, AES key URIs,
  init maps and byte ranges are supported. No ad filtering is performed.
- HLS variables and content steering are explicitly rejected when relay is needed.
  DRM-specific key schemes, DASH manifest rewriting and exhaustive LL-HLS support
  are not implemented.
- Recovery probes a representative attested resource of the failed kind; it does
  not accept a client-provided upstream URL. Selection is currently per resource
  kind, not per individual segment or CDN origin.
- Resolution cookies are not automatically promoted to delivery credentials.
  An adapter must declare delivery headers when the source requires them.
- The registry and compatibility observations are process-local. Multiple workers
  need affinity or a shared registry before they can serve relay capabilities.
- A master 403 at remote egress does not establish that segments require relay.
  Remote playback records each necessary escalation; a browser test with injected
  403s validates that behavior but is not evidence of a real remote CDN response.
