"""Materialized shelf feeds, independent of the replaceable ranking implementation."""
from dataclasses import asdict
from datetime import timedelta
from sqlalchemy import select, func, delete
from fastapi import HTTPException
from db.models.catalog import CatalogEntity, SearchCache
from db.models.profile import utc_now
from activity.service import continue_watching
from metadata.catalog import display
from metadata.search import fingerprint
from recommendations.config import POLICY
from recommendations.taste import build_taste, signal_signature, suppress_consumed
from recommendations.engine import HybridRecommender, LocalCandidates, Ranked, diversify
from recommendations.enrichment import warm


def put(db, key, data, policy):
    row = db.get(SearchCache, key)
    if row:
        row.data, row.expires_at = data, utc_now() + timedelta(minutes=policy.feed_minutes)
    else:
        db.add(SearchCache(key=key, data=data, expires_at=utc_now() + timedelta(minutes=policy.feed_minutes)))
    db.flush()


def localized(profile, en, tr):
    return tr if profile.locale == "tr-TR" else en


def assemble(db, profile, surface, taste, ranked, policy):
    kind = {"home": "all", "movies": "movie", "series": "tv"}[surface]
    shelves, used = [], set()
    all_continued = continue_watching(db, profile, kind)
    used.update(f"{i['media_type']}:{i['tmdb_id']}" for i in all_continued)
    continued = all_continued[:policy.shelf_items]
    continue_items = []
    for item in continued:
        key = f"{item['media_type']}:{item['tmdb_id']}"
        shown = display(db, key, profile.locale) or {"key": key, "kind": item["media_type"],
            "media_type": item["media_type"], "tmdb_id": item["tmdb_id"],
            "title": (item.get("metadata") or {}).get("title", key), "roles": []}
        shown["resume"] = {k: item[k] for k in ("season_number", "episode_number", "position_seconds", "action")}
        continue_items.append(shown)
        used.add(key)
    def add(shelf_id, title, options, personalized=False, count=None, context_key=None):
        if len(shelves) >= policy.max_shelves:
            return
        picked = diversify(options, count or policy.shelf_items, used, policy)
        if not picked:
            return
        items = [display(db, r.candidate.entity.key, profile.locale) for r in picked]
        used.update(r.candidate.entity.key for r in picked)
        shelves.append({"id": shelf_id, "kind": shelf_id.split(":")[0], "title": title,
            "personalized": personalized, "context_key": context_key, "items": items})
    add("hero", localized(profile, "Featured", "Öne çıkan"), ranked, taste.personalized, 1)
    if continue_items:
        shelves.append({"id": "continue", "kind": "continue", "title": localized(profile, "Continue Watching", "İzlemeye Devam Et"),
            "personalized": False, "items": continue_items, "context_key": None})
    if taste.personalized:
        add("recommended", localized(profile, f"Recommended for {profile.name}", f"{profile.name} için önerilenler"), ranked, True)
    for key, _ in taste.sources[:3]:
        label = display(db, key, profile.locale)
        if not label:
            continue
        seed_terms = next((r.candidate.terms for r in ranked if r.candidate.entity.key == key), set())
        if not seed_terms:
            from db.models.catalog import CatalogFeature
            seed_terms = set(db.scalars(select(CatalogFeature.term).where(CatalogFeature.media_key == key)))
        # Content overlap is bounded to the already generated candidate pool.
        source = [r for r in ranked if key in r.candidate.related_to or any(t in seed_terms for t in r.candidate.terms if t.startswith(("keyword:", "director:", "creator:", "genre:")))]
        watched = taste.signals[key]["behavioral"]
        en = "Because you watched " if watched else "Because you selected "
        tr = "İzlediğiniz için: " if watched else "Seçiminize göre: "
        add("because:" + key, localized(profile, en, tr) + label["title"], source, True, context_key=key)
    def unpersonalized(options):
        return [Ranked(r.candidate, r.contributions.get("popularity", 0), r.contributions, r.exclusion) for r in options]
    trending = unpersonalized([r for r in ranked if any("/trending/" in s for s in r.candidate.sources)])
    add("trending", localized(profile, "Trending", "Trendler"), sorted(trending, key=lambda r: (-r.contributions.get("popularity", 0), r.candidate.entity.key)))
    if not taste.personalized:
        add("catalog", localized(profile, "Explore the catalog", "Kataloğu keşfet"), ranked)
    for term in sorted(taste.affinities, key=lambda t: (-taste.affinities[t], t))[:16]:
        prefix, identifier = term.split(":")
        options = [r for r in ranked if term in r.candidate.terms]
        label = term
        if prefix in ("cast", "director", "creator", "producer"):
            person = db.get(CatalogEntity, f"person:{identifier}")
            label = person.name if person else term
        elif prefix in ("genre", "keyword"):
            for r in options:
                refs = r.candidate.entity.features.get("genre_refs" if prefix == "genre" else "keywords", [])
                named = next((f["name"] for f in refs if str(f["tmdb_id"]) == identifier and f.get("name")), None)
                if named:
                    label = named
                    break
        add("theme:" + term, localized(profile, "Explore: ", "Keşfet: ") + label, options, True)
    for media_type in (["movie", "tv"] if kind == "all" else [kind]):
        options = [r for r in ranked if r.candidate.entity.kind == media_type]
        popular = unpersonalized([r for r in options if f"/{media_type}/popular" in r.candidate.sources])
        add("popular:" + media_type, localized(profile, "Popular movies" if media_type == "movie" else "Popular series", "Popüler filmler" if media_type == "movie" else "Popüler diziler"), popular)
        add("more:" + media_type, localized(profile, "More movies" if media_type == "movie" else "More series", "Daha fazla film" if media_type == "movie" else "Daha fazla dizi"), options, taste.personalized)
    return shelves


def current_catalog_signature(db):
    return str(db.scalar(select(func.max(CatalogEntity.updated_at))))


async def feed(db, profile, surface="home", batch_size=3, cursor=None, engine=None, policy=POLICY, enrich=True):
    engine = engine or HybridRecommender(policy)
    scope = {"profile_id": profile.id, "locale": profile.locale, "surface": surface, "batch_size": batch_size}
    signature = signal_signature(db, profile, policy)
    if cursor:
        pointer = db.get(SearchCache, cursor)
        if not pointer or pointer.expires_at <= utc_now() or pointer.data.get("type") != "feed_cursor":
            raise HTTPException(410, "Feed cursor expired; restart the feed")
        if pointer.data["scope"] != scope:
            raise HTTPException(422, "Cursor does not belong to this profile/surface/locale")
        snapshot_id, offset = pointer.data["snapshot_id"], pointer.data["offset"]
        snapshot = db.get(SearchCache, snapshot_id)
        if not snapshot or snapshot.expires_at <= utc_now():
            raise HTTPException(410, "Feed snapshot expired; restart the feed")
        if snapshot.data["signature"] != signature:
            raise HTTPException(409, "Profile activity changed; restart the feed")
    else:
        root = fingerprint({"feed": scope, "signals": signature, "catalog": current_catalog_signature(db), "engine": engine.version, "policy": asdict(policy)})
        snapshot = db.get(SearchCache, root)
        if not snapshot or snapshot.expires_at <= utc_now():
            taste = build_taste(db, profile, policy)
            baseline, warnings = await warm(db, profile, taste, policy) if enrich else ({}, [])
            # Enrichment can supply previously missing seed features.
            taste = build_taste(db, profile, policy)
            kind = {"home": "all", "movies": "movie", "series": "tv"}[surface]
            candidates = LocalCandidates(policy).generate(db, taste, kind, baseline)
            suppress_consumed(db, profile, taste, candidates, policy)
            ranked = engine.rank(taste, candidates)
            data = {"type": "feed_snapshot", "scope": scope, "signature": signature,
                "personalized": taste.personalized, "shelves": assemble(db, profile, surface, taste, ranked, policy),
                "warnings": warnings, "diagnostics": {"engine": engine.version, "enabled_domains": sorted(taste.domains),
                    "source_signals": taste.signals, "affinities": taste.affinities,
                    "candidates": [{"key": r.candidate.entity.key, "score": r.score, "contributions": r.contributions,
                        "sources": sorted(r.candidate.sources), "exclusion": r.exclusion} for r in ranked]}}
            # Materialization key reflects the catalog after warming, not before it.
            root = fingerprint({"feed": scope, "signals": signature, "catalog": current_catalog_signature(db), "engine": engine.version, "policy": asdict(policy)})
            put(db, root, data, policy)
            snapshot = db.get(SearchCache, root)
        snapshot_id, offset = root, 0
    data = snapshot.data
    shelves = data["shelves"][offset:offset + batch_size]
    next_cursor = None
    if offset + batch_size < len(data["shelves"]):
        next_cursor = fingerprint({"feed_snapshot": snapshot_id, "offset": offset + batch_size})
        if not db.get(SearchCache, next_cursor):
            put(db, next_cursor, {"type": "feed_cursor", "scope": scope, "snapshot_id": snapshot_id, "offset": offset + batch_size}, policy)
    db.execute(delete(SearchCache).where(SearchCache.expires_at <= utc_now()))
    db.commit()
    return {"snapshot_id": snapshot_id, "surface": surface, "personalized": data["personalized"],
        "shelves": shelves, "next_cursor": next_cursor, "warnings": data["warnings"]}
