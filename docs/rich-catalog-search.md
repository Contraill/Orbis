# Rich catalog and search foundation

This milestone extends the existing TMDB/localized metadata cache. It adds no
recommendation ranking, personalized feed, anime gate, playback changes, or final
UI design. All catalog entities retain TMDB identity independent of locale.

## Domain and storage

Migration `c42e8a19d730` follows `b91f02a7c640`:

- `catalog_entities`: one `movie:ID`, `tv:ID`, `person:ID`, or `company:ID` key;
  canonical name, normalized features, immutable creation time and refresh time.
- `catalog_links`: media/person/company relationships, role and character;
  reverse credit lookup has a covering entity/role/media index.
- `catalog_seasons` and `catalog_episodes`: series identity, TMDB IDs, numbering,
  dates, counts and applicable runtimes. Season and episode display fields retain
  the existing locale-specific season payload, without duplicating media entities.
- `catalog_ratings`: source/external-ID identity, average, scale, votes,
  provenance and refresh time. No IMDb columns spread through catalog entities.
- `catalog_search_cache`: expiring query results and opaque cursor state.
- `catalog_fts`: FTS5 documents with searchable names and normalized trigrams.
  Alembic deliberately excludes this managed virtual table and its shadow tables
  from schema autogeneration; it still checks the ordinary catalog tables.

The pre-existing `localized_metadata` table remains authoritative for localized
presentation. Keys are `(content_key, locale)`. English and Turkish fetches never
replace each other's records. Rich responses preserve title, original title,
overview, image URLs, dates, named genre references, keywords, aliases, external
IDs, companies, cast/characters, crew/jobs, creators, videos and season summaries.
Videos retain site, key, language, country, type, official flag and publication
time. Related titles are references, not copied full payloads.

Canonical features expose TMDB genre and keyword IDs, original language,
countries, media type, companies and credit relationships. Genre/keyword names
are descriptive; future feature matching should use IDs. These features support
later explicit anime-interest gating, but this milestone does not apply it.

## Fetching and localization

TMDB detail requests append credits, keywords, external IDs, alternative titles,
videos, similar titles and recommendation references. Only normalized fields are
stored; raw TMDB responses are not archived. Related-title references are metadata,
not an Orbis recommendation engine.

Detail and season cache lifetime is 24 hours per locale. Older, pre-milestone
detail payloads are enriched on their next detail request. A search summary cannot
erase rich details or extend their freshness. The migration backfills the index
from existing localized records without a network fetch.

Search display prefers the active profile locale, then English, then Turkish,
then the canonical name. `display_locale` discloses a fallback. Both languages,
original titles and aliases remain searchable regardless of profile locale.
Fetching the other locale's detail response enriches that localization; there is
no automatic two-language download for every remote search hit.

Search/trending summaries populate the cache; opening details adds rich features.
Person credit expansion fetches `combined_credits`, stores media summaries and
role relationships, and caches completion for 30 minutes. Unknown remote person
roles remain empty until authoritative credits are fetched; `known_for` is not
misrepresented as proof of a particular job.

## Search behavior and bounds

Names use Unicode case folding, NFKD diacritic removal, Turkish dotted/dotless-I
normalization and punctuation-to-space normalization. Each media document includes
both localized titles, its original title, aliases, credited people and companies.
People and companies also have independently addressable documents.

FTS5 prefix retrieval selects at most 300 candidates. A trigram-token FTS query
selects at most another 300 candidates for misspellings that fail prefix matching.
Only that union is fuzzy-ranked with standard-library `SequenceMatcher`, with
exact/prefix/substring preference and a 68-point threshold. Equal scores prefer
an exact display-title match in the profile locale, then break ties by canonical
key. Query token and trigram counts are bounded. There is no fuzzy scan of all
catalog rows and no new runtime dependency or search service.

This is deliberately bounded approximate search: at most 600 local candidates,
not an exhaustive result set for broad common terms. Scores are relevance hints,
not probabilities. Typo matching works on locally cached metadata; TMDB itself
controls behavior for an unseen misspelled name. The included tests cover 1,200
background titles, the requested misspellings, roles and cross-language matches.

## APIs

Existing numbered `/api/catalog/search` and `/trending` remain compatible for
existing callers. They retain their TMDB-backed behavior. The verification UI uses
the new unified search endpoint instead.

`GET /api/catalog/unified-search`

- `query`: 1–200 characters, nonblank after normalization.
- `kind`: `all`, `movie`, `tv`, `person`, or `company`.
- `profile_id`: uses that profile's locale; otherwise `locale=en-US|tr-TR` or the
  installation default applies.
- `limit`: 1–50, default 20.
- `online`: default false. Local matches serve first. A local miss automatically
  tries TMDB for queries of at least three normalized characters. Set true to
  continue beyond cached matches into TMDB even when local results exist.
- `cursor`: opaque token returned as `next_cursor`.

The response has `results`, per-page `groups` (`movie`, `tv`, `person`, `company`),
`next_cursor`, `warning` and `candidate_limit`. Every result has a canonical key,
kind, TMDB ID, display title and roles, plus media presentation fields where known.

All-domain remote search combines TMDB multi-search and company search. Each
client page consumes at most one upstream page per search domain. Upstream page
numbers advance to TMDB's own maximum of 500. Local/remote duplicates are removed
by canonical key, including repeated upstream entries. An empty duplicate-only
page can have `next_cursor`; clients must use cursor presence to detect completion.

Search cursors hold an ordered display snapshot plus pending upstream page and
seen identities. Replaying a successful cursor returns the same page. The query,
locale, kind, limit and online flag must remain unchanged (422 on mismatch).
Cursors expire after 30 minutes (410: restart the query). Queries, empty results
and completed pages share this 30-minute cache. Expired records are pruned on
search. Upstream failures return a warning/retry cursor and are not negative-cached.
New metadata does not reorder an already-cached search; a newly enriched match may
therefore become visible after the search-cache lifetime.

`GET /api/catalog/items?kind=all|movie|tv`

Shared local catalog query for Home, Movies and Series. Supports the same locale,
limit and opaque cursor conventions, plus `my_list=true&profile_id=ID`. My List
filters only explicit library intent. It includes locally cached catalog items;
the existing library API remains the complete saved-ID source. This endpoint is
unranked, ordered by canonical key, and uses indexed keyset pagination with an
immutable creation-time boundary. Concurrent inserts cannot enter an existing
traversal. Changes to library membership may affect subsequent pages; this is not
a transaction-long snapshot of user actions.

`GET /api/catalog/person/{id}/credits?enrich=true`

Optionally fetch and persist TMDB combined credits, then use shared local catalog
pagination. Each media result includes the person's roles for that title.
`GET /api/catalog/company/{id}/credits` provides local company-linked titles.
Company-wide remote filmography discovery is not implemented.

Existing movie, TV and season detail URLs return the richer normalized schema.
`GET /api/catalog/{movie|tv}/{id}/ratings` returns source-attributed cached ratings.

## Optional IMDb import

IMDb's non-commercial ratings dataset has `tconst`, `averageRating`, and `numVotes`:
https://developer.imdb.com/non-commercial-datasets/

After obtaining `title.ratings.tsv.gz` under its applicable terms, run inside the
backend environment with the intended `DATABASE_URL`:

```sh
python -m metadata.ratings /path/to/title.ratings.tsv.gz
```

The importer streams gzip/TSV rows and upserts only IDs already present in Orbis.
Memory scales with the local catalog's IDs, not the IMDb dataset. An empty local
IMDb-ID set exits immediately. The import is transactional and validates rating
bounds. Source, dataset URL and import time are retained. Re-running updates cached
ratings; rerun after catalog growth to include new IDs. Missing rows retain previous
cached ratings with their original timestamps.

No automatic dataset download, scheduling or startup dependency was added. No
Rotten Tomatoes integration or scraping exists. No real IMDb dataset was downloaded
for verification; ingestion was tested with a small compressed fixture.

## Verification UI and tests

Home has a submit-driven verification search with domain selection, explicit TMDB
expansion, grouped results, load-more and person/company credit discovery. Switching
profiles or locale resets it. Detail pages expose an expandable normalized JSON
response. There is no trailer UI or cinematic redesign.

Verification on native aarch64 Raspberry Pi:

- Full backend suite: 107 tests passed.
- Fresh Alembic upgrade, older profile/playback upgrade, bilingual catalog backfill
  and Alembic schema drift checks passed within that suite.
- Frontend TypeScript check and production Vite build passed in ARM64 Docker.
- ARM64 backend image built and started against a fresh temporary SQLite database;
  health returned 200, zero profiles were created, and offline search returned 200
  with a controlled missing-TMDB warning.
- Production bundle retains the existing large Shaka chunk warning.
- No playback/live-provider browser tests were run. UI browser interaction and live
  TMDB integration were not exercised; API tests use deterministic upstream fixtures.
- `git diff --check` passed. No live database, Git metadata, remotes or host network
  configuration were modified.

Implementation lives in `app/backend/db/models/catalog.py`,
`app/backend/metadata/{catalog,index,search,ratings,schemas,tmdb,localization}.py`,
`app/backend/api/catalog.py`, the catalog migration, model registration and Alembic
environment. Tests are in `test_rich_catalog.py`, `test_migrations.py` and
`test_database_and_api.py`. Frontend changes are in `api.ts`, `HomePage.tsx`,
`SearchVerification.tsx` and `DetailPage.tsx`.

Recommended next milestone: implement the separately scoped hybrid content and
engagement recommender with explicit anime-interest eligibility and cold-start
behavior, using canonical feature IDs and the existing engagement signals. Keep
that work independent of the later final UI redesign.
