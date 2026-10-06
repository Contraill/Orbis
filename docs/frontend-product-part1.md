# Orbis product frontend · Part 1

The consumer frontend uses the frozen Backend V1 APIs. The final fullscreen player
is documented separately in `frontend-player-v1.md`.

## Architecture and routes

- `app/SetupGate` handles an English first screen, language choice, owner bootstrap,
  and the initial profile wizard. A dedicated taste screen then records up to five
  onboarding choices. The pending taste step is remembered in browser storage until
  finished or skipped; Backend V1 has no separate onboarding-completed field.
- `catalog/ProfileSelection`, `app/ProfileWizard`, `app/TasteSelection`,
  `app/ProfileEditor` and `app/ProfileSettings` handle profile choice, creation,
  one-time taste selection and later preferences. Blobatar renders locally from the
  stored `avatar_seed`; renaming retains that seed. Before profile selection, the
  owner profile locale determines the UI language. Owner administration still
  requires an authenticated owner session after opening the Admin entry.
- `app/AppHeader` and `app/useDirectionalFocus` provide desktop/mobile navigation,
  profile menu, visible focus and directional keyboard movement. A future Tizen or
  webOS wrapper can map remote keys onto the same DOM keyboard semantics.
- `/`, `/movies`, `/series` use one `InfiniteShelfFeed` with the V1 feed surface
  parameter. It renders a Hero, bounded horizontal shelves and one Continue card
  per canonical series. An IntersectionObserver requests the next shelf batch;
  the explicit button supports keyboard/TV input. Adjacent shelf IDs are deduped,
  stale cursor 409/410 restarts the feed, and exhausted feeds stop requesting.
- `/library` uses only the explicit My List endpoint. It filters All/Movies/Series
  and renders at most 24 entries initially, with client continuation.
- `/search` uses unified V1 search: 360 ms debounce, aborting stale queries,
  local results before TMDB fallback, grouped media/people/companies and cursor
  continuation. A deliberate wider-catalog action expands a successful local
  search without calling TMDB on each keystroke. Person/company credits load
  locally before optional enrichment.
- `/movie/:id` and `/tv/:id` use rich catalog details, optional ratings, watch state,
  Continue state, seasons and related references. They show a backdrop immediately.
  YouTube trailers use the IFrame API with a privacy-enhanced host; it is revealed only after
  a playing event, so blocked/offline autoplay leaves the backdrop intact. Mute is
  a single accessible toggle and never resets the iframe on unrelated renders.
- `RouteScroll` restores position on browser back; a small per-profile feed cache
  retains shelves for two minutes and is cleared by My List, Not Interested,
  onboarding/profile changes and return from playback. No player or admin bundle
  loads during initial browse.

## Design system

`src/product.css` defines navy surfaces, cyan/teal highlights, spacing, focus,
poster size, glass only on the header/menu, reduced-motion behavior, and desktop,
mobile and large-TV breakpoints. Gradients and a subtle orbital arc are reusable
background layers. Final assets in `public/brand/` supply the desktop wordmark,
compact icon and favicon; the artwork is never reconstructed as text/CSS.
`app/i18n.ts` is the shared English/Türkçe UI dictionary. Profile locale selects
both UI language and backend localized catalog response; TMDB identity stays fixed.

## Precise V1 gaps to consider later

- `GET /api/library/profiles/{id}/my-list` returns an unpaginated array. The UI
  limits mounted cards in groups of 24, but a very large list still arrives in
  one API response. A future cursor contract would solve the fetch bound.
- V1 has `PUT /not-interested` but no read endpoint for current negative state.
  The detail action can undo within the current page session; after reopening,
  the button cannot show a persisted checked state. Recommendation suppression
  itself remains backend owned and works.
- Feed Continue items contain position but not duration. The UI reads the
  existing Continue Watching endpoint once per surface for accurate progress bars.
- Trailer embedding depends on the video site's permitted iframe behavior and
  browser autoplay policy. Offline or blocked embeds leave the cinematic backdrop;
  an external provider may still show its mandatory embed chrome.

## Verification fixtures

`tests/profile-foundation.mjs` uses the isolated `backend/tests/browser_fixture.py`
API for first run, five favorites, profile changes, My List/Continue, locale and
admin boundary. `tests/product-smoke.mjs` uses a disposable V1 backend populated
with synthetic canonical catalog records. It covers feed shelf continuation,
scoped browse, typo/person search, credits, detail, list, playback entry, season
selection, locale and overflow at desktop/mobile/TV sizes. Neither test contacts a
live provider or the private installation.
