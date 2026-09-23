# Hybrid recommendations and shelf feeds

Orbis now has a provider-independent content + engagement recommender and a shared
Home / Movies / Series feed service. It does not use collaborative filtering,
external ML services, Redis, playback-save frequency, or provider/source identity.

## Architecture and replaceability

`recommendations/` contains the following stages:

1. `enrichment.py`: optional, cached, bounded TMDB warming.
2. `engine.LocalCandidates`: candidate generation from the inverted feature index,
   cached related-title references, cached upstream lists and the local catalog.
3. `taste.py`: aggregate durable behavioral evidence at canonical movie/series level.
4. `HybridRecommender.rank`: inspectable feature/taste scoring, content-domain
   eligibility, Not Interested and lifecycle suppression, deterministic ordering.
5. `diversify`: bounded relevance-preserving diversity and canonical deduplication.
6. `feeds.py`: shared shelf assembly, localized presentation and materialization.

`Recommender` and `CandidateGenerator` protocols specify domain boundaries. The
FastAPI `api.feeds.recommender` dependency can be replaced while retaining the feed
contract. Feed assembly consumes ranked canonical candidates, not provider objects.

`config.py` centralizes weights, thresholds, limits, recency, diversity and cache
policy. Engine version and policy values participate in materialization keys.
Diagnostics expose source signals, affinities, candidate generators, component
scores and exclusions. They are requested separately from normal feed responses.

## Candidate generation and metadata

`catalog_features(term, media_key)` is a derived inverted index over the existing
canonical catalog, not a separate catalog. Terms include genres, keywords,
cast, directors, creators, producers, companies, collection and classified domain.
It has a composite primary key for term lookup and a reverse media-key index.
Catalog ingest and person-credit enrichment keep it current. Migration
`d53f9b20e841` backfills it and adds catalog-refresh and profile/media history indexes.
The previous catalog migration explicitly skips this later derived index while
backfilling older installations before its table exists.

Movie collection IDs support franchise diversity. TMDB search/list summaries now
retain genre IDs, original language/countries and popularity so safe domain
classification does not require a separate detail request for every poster.

Candidate sources are:

- Indexed overlap with up to 40 strongest taste features, at most 200 matches.
- Up to 40 cached related references per positive source, at most 12 taste sources.
- Cached TMDB movie/TV trending and popular lists.
- Cached recommendation/similar pages for up to two positive seed/source titles.
- Up to 100 recently cached local titles as an offline fallback.

The merged canonical candidate universe is capped at 400 before scoring.
Feature lookup uses indexed postings rather than scanning every catalog entity.
This bounded approximation can omit relevant titles in very large catalogs.

TMDB warming uses English canonical enrichment regardless of display locale.
Existing Turkish metadata is preserved and preferred for Turkish display. Warming
allows at most 10 requests per new materialization, with concurrency 2 and a
3-second timeout per call. It fetches at most one 20-result page per list source.
Positive source pages cache for 12 hours; failures cache for 5 minutes. Detail
requests reuse the existing 24-hour detail cache. Warming never runs during cursor
continuation, and network failure falls back to the local pool with warnings.
A cold household with no catalog and no available TMDB may have an empty feed.

Relevant TMDB references:
[Trending movies](https://developer.themoviedb.org/reference/trending-movies),
[Popular movies](https://developer.themoviedb.org/reference/movie-popular-list),
[Movie recommendations](https://developer.themoviedb.org/reference/movie-recommendations).

## Taste and engagement

Taste aggregation reads up to 1,000 recently active durable progress records and
corresponding meaningful activity days, plus onboarding and explicit intents.
Multiple TV episodes are aggregated to the series identity.

Default positive weights are onboarding 3, completion 5, sustained progression 5,
My List 4, rewatch 3 (capped at two), substantial viewing 1.5 and repeated meaningful
active days 1 (capped at two additional days). Substantial viewing begins at 20
minutes. Sustained TV progression requires at least two episodes with ten minutes
of evidence each, on at least two meaningful active days. Weekly viewing qualifies.
Meaningful recorded completion also works for shorter episodes.

Onboarding decays gradually as the number of meaningfully engaged titles grows;
one playback event does not remove initial preferences. Behavioral evidence has a
120-day exponential recency scale with a 0.4 floor. Brief starts create no positive
affinity. A 30-day abandoned start incurs a 1.5 title penalty rather than a permanent
ban or broad genre dislike. Not Interested is a hard title exclusion and contributes
no positive affinity, including when the title is also an onboarding seed.

Genre/keyword/person/company affinity aggregates positive source weights using
canonical IDs. Candidate scores report those feature contributions separately,
plus related-onboarding/engagement similarity, popularity, My List and stale penalty.
Popularity is capped so it cannot overpower meaningful content affinity.

Completed/highly watched movies, onboarding seed titles and seen/active series are
suppressed from discovery. A candidate-bounded lookup of all durable history also
suppresses consumed titles older than the taste window. Rewatch strengthens taste,
but v1 does not add a dedicated rewatch shelf. Continue Watching is a separate resume
utility; its state is not treated as liking a title. Explicitly hidden resume items
stay hidden under the existing library rules.

## Anime and domain eligibility

`DomainEligibility` is the reusable gate. Anime is classified from an explicit
anime/Japanese-animation keyword, or TMDB Animation genre 16 together with Japanese
original language or production/origin country. Japanese live action is not anime.
Generic non-Japanese Animation is not anime.

A profile earns anime eligibility through a known-anime onboarding selection,
My List addition, meaningful completion, sustained progression, rewatch, or at least
20 minutes of accumulated viewing. A brief start does not qualify. Not Interested
overrides that title's positive evidence.

All discovery shelves in these profile feeds, including their filtered trending
rows, apply eligibility. Resume utility, explicit My List, catalog browsing and
search remain available independently of this gate. Unknown-domain titles, and
Animation missing language/country evidence, are withheld from discovery until
metadata can resolve classification. This is conservative metadata-based
classification, not a perfect cultural taxonomy or a parental-control system.

## Deduplication and diversity

Identity is always `movie:TMDB_ID` or `tv:TMDB_ID`. There are no episode recommendations.
Candidate source duplicates merge. Feed assembly reserves all Continue Watching
identities, and every displayed item appears at most once in a feed snapshot,
including across pages. A new snapshot can naturally repeat earlier discoveries.

Each row uses deterministic maximal-marginal-relevance-style selection within a
relevance window. Repeated collection/franchise, genre, cast/director/creator and
media type incur soft penalties. Comparable movie and TV candidates can mix in Home.
The relevance floor prevents a highly irrelevant title from winning merely to
increase variety. A sparse or homogeneous catalog can still produce similar picks.
Trending/popular rows use popularity ordering with the same safety, seen and diversity
filters, rather than disguising a taste score as global popularity.

## Feed API and continuation

`GET /api/feeds/profiles/{profile_id}/{surface}`

- `surface`: `home`, `movies`, or `series`.
- `batch_size`: 1–5 shelves, default 3.
- `cursor`: optional opaque continuation token.

Response fields: `snapshot_id`, `surface`, `personalized`, `shelves`,
`next_cursor`, and upstream-availability `warnings`. A shelf has stable `id`, `kind`,
localized `title`, `personalized`, optional `context_key`, and `items`.
Items use the canonical catalog display contract; Continue Watching adds a bounded
`resume` object without a provider URL.

Home permits movies and TV; Movies and Series filter both discovery and Continue
Watching to their media type. Assembly can produce a featured item, Continue
Watching, profile recommendations, up to three Because You Watched/Selected rows,
Trending, dynamic genre/keyword/person/company themes, popular and further discovery
rows. Empty rows are omitted. There are at most 14 shelves and six items per normal
shelf; default batches therefore load at most 18 posters, maximum batches 30.
A cold profile without established affinity gets honest catalog/trending discovery
rather than a row falsely labeled personalized.

The existing `/api/library/profiles/{id}/my-list?kind=all|movie|tv` remains the
explicit saved-content API. Feeds have no My List surface and do not inject Continue
Watching into that list. The minimal library UI now also omits its Continue shelf.

`GET /api/feeds/profiles/{id}/diagnostics/{snapshot_id}` returns the separately stored
scoring diagnostics for that profile. It follows the application's existing local
profile-selection access model; it is not a new private-profile authentication system.

## Cache and invalidation contract

Feed snapshots and cursor pointers use the existing SQLite expiring cache table.
A materialization lasts 20 minutes. Its key includes profile, signal signature,
locale, surface, batch size, catalog refresh signature, engine version and policy.
The signature includes explicit intents, onboarding, completion/rewatch totals,
meaningful activity-day counts and ten-minute accumulated-viewing buckets. It does
not count raw save requests. A daily boundary updates time-sensitive penalties.

Scrolling reads cached shelves and checks inexpensive profile aggregates; it does
not rebuild taste/candidates or make TMDB requests. Successful cursor replay is
identical while the profile signal signature remains unchanged. Catalog enrichment
does not reorder an existing traversal.

- 422: cursor belongs to a different profile, locale, surface or batch size.
- 409: meaningful profile signals or feedback changed; restart at the root.
- 410: snapshot/cursor expired; restart at the root.
- `next_cursor: null`: clean exhaustion; no artificial endless repetition.

Invalidation deliberately takes precedence over replay after feedback, so a newly
disliked title cannot leak into later batches of an old discovery snapshot. Profile
locale changes only presentation/cache scope, not canonical taste or scoring.
New root requests reuse the cache; the UI Refresh button is not a forced upstream
cache bypass. Upstream recovery can therefore wait until the feed snapshot expires.
Resume positions are snapshotted; the existing resume endpoint remains authoritative.

## Verification UI

Home, Movies and Series share `FeedVerification.tsx`, existing poster components
and styles. It renders shelves, load-more, resume/hide, My List and Not Interested
buttons, a refresh action, and an optional scoring diagnostics panel. Profile,
locale and surface changes reset pending requests and continuation. The existing
catalog search verification remains accessible below the feed, including anime
search regardless of recommendation eligibility. There is no final visual redesign.

## Verification and limitations

Automated verification covers cold start with zero/five seeds, meaningful versus
brief engagement, stale starts, weekly TV progression, rewatch, My List, explicit
negative feedback, profile isolation, localized display with canonical scoring,
anime and generic Animation, all-history seen suppression, indexed bounded
candidate sets, deterministic diversity, surface and Continue Watching scope,
My List independence, cursor replay/exhaustion/isolation and signal invalidation.
Fresh and existing-data migration/backfill tests include schema drift checking.

Final verification results:

- Full backend suite: **135 tests passed**.
- Frontend TypeScript check and Vite production build: **passed**. The existing
  large Shaka chunk and upstream React Router directive warnings remain.
- Fresh database migration, legacy profile/playback upgrade, bilingual catalog
  backfill, recommendation-index backfill and Alembic drift checks: **passed**.
- Native ARM64 backend and frontend build images: **built successfully**.
- Isolated ARM64 backend startup: health passed; fresh database had zero profiles;
  migration head was `d53f9b20e841`.
- Runtime fixture traversal: Home produced 6 shelves/29 unique titles, Movies
  4 shelves/14 movie titles, Series 4 shelves/15 TV titles. All traversals exhausted
  cleanly with correct media scope and no duplicate titles.
- `git diff --check`: **passed**.

A read-only live TMDB smoke test succeeded for Interstellar (157336): genres,
546 credit entries and external-ID source names normalized successfully; the
trending and recommendations endpoints each returned 20 items. It used the existing
credentials without displaying secrets or modifying the live database. External
availability is not required by the test suite.

Remaining limitations: metadata-based anime classification can be incomplete;
unknown domains are withheld, remote related/catalog expansion is deliberately
small, taste has a recent-history bound, diversity is soft, and there is no dedicated
rewatch row. No frontend browser interaction was automated in this milestone;
API behavior and frontend compilation/build are verified separately. No provider or
playback browser tests were run. No live deployment/database, Git metadata/remotes,
or host network/Tailscale/DNS/routing settings were changed.

Recommended next milestone: a measured recommendation-quality pass with household
feedback and richer catalog warming, followed by the separately scoped final
Home/Movies/Series and cinematic detail UI. The backend contracts now support that
work without coupling it to providers or a particular ranking implementation.

## Changed modules

New backend modules are `recommendations/{config,features,taste,engine,enrichment,
feeds,schemas}.py`, package initialization, `api/feeds.py`, and migration
`d53f9b20e841_recommendations.py`. Existing catalog models/ingest/TMDB normalization,
person-credit enrichment, history indexing and router registration were extended.
The previous catalog migration was adjusted only to avoid indexing a table that is
created by the following migration. Tests cover recommendations, API integration
and migration upgrades.

Frontend changes are `FeedVerification.tsx`, the shared `HomePage.tsx`, feed API
contracts in `api.ts`, Movies/Series routes and navigation, and removal of the
Continue Watching shelf from `LibraryPage.tsx`. No playback/provider implementation
was changed.
