"""Canonical feature extraction and reusable content-domain policies."""
from sqlalchemy import delete, select
from db.models.catalog import CatalogEntity, CatalogLink, CatalogFeature
from metadata.index import normalize


def domain(features):
    genres = {g["tmdb_id"] for g in features.get("genre_refs", [])}
    keywords = {normalize(k.get("name", "")) for k in features.get("keywords", [])}
    if keywords & {"anime", "japanese animation"}:
        return "anime"
    if 16 in genres:
        if features.get("original_language") == "ja" or "JP" in features.get("countries", []):
            return "anime"
        if not features.get("original_language") and not features.get("countries"):
            return "unknown_animation"
    if not genres:
        return "unknown"
    return "general"


def extract(features, links=()):
    terms = set()
    for key, prefix in (("genre_refs", "genre"), ("keywords", "keyword")):
        terms.update(f"{prefix}:{r['tmdb_id']}" for r in features.get(key, []))
    roles = {"Actor": "cast", "Director": "director", "Creator": "creator", "Producer": "producer", "Executive Producer": "producer", "Production company": "company"}
    for link in links:
        prefix = roles.get(link.role)
        if prefix:
            terms.add(f"{prefix}:{link.entity_key.split(':')[1]}")
    if features.get("collection_id"):
        terms.add(f"collection:{features['collection_id']}")
    terms.add(f"domain:{domain(features)}")
    return terms


def reindex_features(db, key):
    row = db.get(CatalogEntity, key)
    if not row or row.kind not in ("movie", "tv"):
        return
    links = db.scalars(select(CatalogLink).where(CatalogLink.media_key == key)).all()
    db.execute(delete(CatalogFeature).where(CatalogFeature.media_key == key))
    db.add_all(CatalogFeature(term=term, media_key=key) for term in sorted(extract(row.features, links)))
    db.flush()


class DomainEligibility:
    """Future domains can be added here without changing ranking or feed APIs."""
    def reason(self, content_domain, enabled_domains):
        if content_domain == "anime" and "anime" not in enabled_domains:
            return "anime_interest_required"
        if content_domain in ("unknown", "unknown_animation"):
            return "insufficient_domain_metadata"
        return None
