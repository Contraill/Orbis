"""Optional, bounded upstream warming; never called by cursor continuation."""
import asyncio
from datetime import timedelta
from sqlalchemy.dialects.sqlite import insert
from db.models.catalog import CatalogEntity, SearchCache
from db.models.profile import utc_now
from metadata.catalog import cached
from metadata.localization import store_metadata
from metadata.search import fingerprint
from metadata.tmdb import TMDBClient, TMDBError, catalog_item
from recommendations.config import POLICY


def source_key(path):
    return fingerprint({"recommendation_source": path, "locale": "en-US"})


def source_cache(db, path):
    row = db.get(SearchCache, source_key(path))
    return row.data if row and row.expires_at > utc_now() else None


def save_source(db, path, value, success, policy):
    expires = utc_now() + (timedelta(hours=policy.upstream_hours) if success else timedelta(minutes=5))
    db.execute(insert(SearchCache).values(key=source_key(path), data=value, expires_at=expires).on_conflict_do_update(
        index_elements=["key"], set_={"data": value, "expires_at": expires}))


async def warm(db, profile, taste, policy=POLICY, client=None):
    client = client or TMDBClient("en-US")
    baseline = ["/trending/movie/week", "/trending/tv/week", "/movie/popular", "/tv/popular"]
    seeds = [f"/{s['media_type']}/{s['tmdb_id']}" for s in profile.onboarding_seeds[:5] if f"{s['media_type']}:{s['tmdb_id']}" not in taste.excluded]
    seeds += ["/" + key.replace(":", "/") for key, _ in taste.sources[:3]]
    requested = list(dict.fromkeys(seeds + baseline))
    # Cached recommendation references add a small amount of rich enrichment.
    for key, _ in taste.sources[:2]:
        row = db.get(CatalogEntity, key)
        for ref in (row.features.get("related", []) if row else [])[:2]:
            requested.append(f"/{ref['media_type']}/{ref['tmdb_id']}")
    pending = []
    for path in dict.fromkeys(requested):
        if source_cache(db, path):
            continue
        if path not in baseline:
            kind, tmdb_id = path.strip("/").split("/")
            if cached(db, f"{kind}:{tmdb_id}", "en-US", details=True):
                continue
        pending.append(path)
    semaphore = asyncio.Semaphore(2)
    def is_list(path):
        return path in baseline or path.endswith(("/recommendations", "/similar"))

    async def fetch(path):
        async with semaphore:
            try:
                if is_list(path):
                    value = await asyncio.wait_for(client._get(path, {"page": 1}), policy.upstream_timeout)
                else:
                    kind, tmdb_id = path.strip("/").split("/")
                    operation = client.movie_details if kind == "movie" else client.tv_details
                    value = await asyncio.wait_for(operation(int(tmdb_id)), policy.upstream_timeout)
                return path, value, None
            except (TMDBError, TimeoutError) as exc:
                return path, None, exc.detail if isinstance(exc, TMDBError) else "TMDB warming timed out"
    async def fetch_and_store(paths):
        responses = await asyncio.gather(*(fetch(p) for p in paths))
        for path, value, error in responses:
            keys = []
            if not error:
                if is_list(path):
                    kind = "movie" if "movie" in path else "tv"
                    for raw in value.get("results", [])[:20]:
                        item = catalog_item({**raw, "media_type": kind})
                        if item:
                            store_metadata(db, "en-US", item)
                            keys.append(f"{kind}:{item.tmdb_id}")
                else:
                    store_metadata(db, "en-US", value)
                    keys.append(f"{value.media_type}:{value.tmdb_id}")
            save_source(db, path, {"keys": keys, "warning": error}, not error, policy)
        db.commit()

    first_batch = pending[:policy.upstream_budget]
    await fetch_and_store(first_batch)
    # A small second phase can turn seed references into searchable summaries in
    # the same cold-start request, sharing the original network request budget.
    positive_paths = list(dict.fromkeys(seeds))[:2]
    relations = [p + "/" + relation for p in positive_paths for relation in ("recommendations", "similar")]
    missing = [p for p in relations if not source_cache(db, p)]
    await fetch_and_store(missing[:max(0, policy.upstream_budget - len(first_batch))])
    sources, warnings = {}, []
    for path in baseline + relations:
        value = source_cache(db, path)
        if value:
            sources[path] = value.get("keys", [])
            if value.get("warning"):
                warnings.append(value["warning"])
    return sources, sorted(set(warnings))
