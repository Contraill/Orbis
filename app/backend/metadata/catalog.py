"""Write-through canonical cache. Localizations retain their independent lifetime."""
from datetime import timedelta
from sqlalchemy import select
from db.models.catalog import CatalogEntity, CatalogLink, CatalogRating, CatalogSeason, CatalogEpisode
from db.models.foundation import LocalizedMetadata
from db.models.profile import utc_now
from metadata.index import reindex

FEATURES = ("genre_refs", "keywords", "aliases", "external_ids", "original_language", "countries", "runtime_minutes", "related")


def entity(db, kind, tmdb_id, name, features=None):
    key = f"{kind}:{tmdb_id}"
    row = db.get(CatalogEntity, key)
    if row is None:
        row = CatalogEntity(key=key, kind=kind, tmdb_id=tmdb_id, name=name, features=features or {})
        db.add(row)
    else:
        previous = row.name
        row.name = name or previous
        merged = {**row.features, **(features or {})}
        if previous != row.name and kind in ("person", "company"):
            merged["aliases"] = sorted(set(merged.get("aliases", []) + [previous]))
        row.features = merged
        row.updated_at = utc_now()
    db.flush()
    return row


def ingest(db, data):
    if "series_tmdb_id" in data:
        key = f"tv:{data['series_tmdb_id']}"
        if not db.get(CatalogEntity, key):
            entity(db, "tv", data["series_tmdb_id"], f"TV {data['series_tmdb_id']}")
        season = db.get(CatalogSeason, (key, data["season_number"]))
        if not season:
            season = CatalogSeason(series_key=key, season_number=data["season_number"], tmdb_id=data["season_tmdb_id"])
            db.add(season)
        season.air_date = data.get("air_date")
        season.episode_count = len(data.get("episodes", []))
        for e in data.get("episodes", []):
            episode = db.get(CatalogEpisode, (key, data["season_number"], e["episode_number"]))
            if not episode:
                episode = CatalogEpisode(series_key=key, season_number=data["season_number"], episode_number=e["episode_number"])
                db.add(episode)
            episode.tmdb_id = e.get("tmdb_id")
            episode.air_date = e.get("air_date")
            episode.runtime_minutes = e.get("runtime_minutes")
        db.flush()
        return
    if "media_type" not in data:
        return
    key = f"{data['media_type']}:{data['tmdb_id']}"
    old = db.get(CatalogEntity, key)
    features = {k: data[k] for k in FEATURES if k in data}
    # Alias sets are additive across locale detail fetches.
    if old:
        features["external_ids"] = {**old.features.get("external_ids", {}), **features.get("external_ids", {})}
        features["aliases"] = sorted(set(old.features.get("aliases", []) + features.get("aliases", [])))
    row = entity(db, data["media_type"], data["tmdb_id"], data.get("original_title") or data["title"], features)
    for season in data.get("seasons", []):
        row_season = db.get(CatalogSeason, (key, season["season_number"]))
        if not row_season:
            row_season = CatalogSeason(series_key=key, season_number=season["season_number"], tmdb_id=season["tmdb_id"])
            db.add(row_season)
        row_season.air_date = season.get("air_date")
        row_season.episode_count = season.get("episode_count")
    if "credits" in data:
        # A localized refresh must not erase roles learned from another locale.
        for c in data["credits"]:
            person = entity(db, "person", c["tmdb_id"], c["name"])
            identity = (key, person.key, c["role"], c.get("character") or "")
            if not db.get(CatalogLink, identity):
                db.add(CatalogLink(media_key=key, entity_key=person.key, role=c["role"], character=c.get("character") or ""))
            reindex(db, person.key)
    for c in data.get("production_companies", []):
        company = entity(db, "company", c["tmdb_id"], c["name"])
        if not db.get(CatalogLink, (key, company.key, "Production company", "")):
            db.add(CatalogLink(media_key=key, entity_key=company.key, role="Production company", character=""))
        reindex(db, company.key)
    db.flush()
    reindex(db, row.key)


def cached(db, key, locale, details=False):
    row = db.get(LocalizedMetadata, (key, locale))
    if row and row.fetched_at > utc_now() - timedelta(hours=24) and (not details or "credits" in row.data):
        return row.data
    return None


def display(db, key, locale):
    row = db.get(CatalogEntity, key)
    if not row:
        return None
    result = {"key": key, "kind": row.kind, "tmdb_id": row.tmdb_id, "title": row.name, "roles": []}
    if row.kind in ("movie", "tv"):
        preferred = db.get(LocalizedMetadata, (key, locale))
        fallback = preferred or db.get(LocalizedMetadata, (key, "en-US")) or db.get(LocalizedMetadata, (key, "tr-TR"))
        if fallback:
            result.update({k: v for k, v in fallback.data.items() if k in ("title", "original_title", "overview", "poster_url", "backdrop_url", "release_date", "vote_average")})
            result["display_locale"] = fallback.locale
        result["media_type"] = row.kind
    else:
        result["roles"] = sorted(set(db.scalars(select(CatalogLink.role).where(CatalogLink.entity_key == key))))
    return result


def ratings(db, key):
    row = db.get(CatalogEntity, key)
    ids = row.features.get("external_ids", {}) if row else {}
    results = []
    for source, external_id in ids.items():
        value = db.get(CatalogRating, (source, external_id))
        if value:
            results.append({"source": value.source, "external_id": value.external_id, "average": value.average, "votes": value.votes, "scale": value.scale, "provenance": value.provenance, "fetched_at": value.fetched_at.isoformat()})
    return results
