"""Unified local-first search with opaque, expiring, replayable cursor pages."""
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete, select
from db.models.catalog import SearchCache, CatalogEntity, CatalogLink
from db.models.foundation import LibraryIntent
from db.models.profile import utc_now
from metadata.catalog import display, entity
from metadata.index import candidates, normalize, reindex
from metadata.localization import store_metadata
from metadata.tmdb import catalog_item, TMDBError

TTL = timedelta(minutes=30)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(db, key, data):
    from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(SearchCache).values(key=key, data=data, expires_at=utc_now() + TTL).on_conflict_do_update(index_elements=["key"], set_={"data": data, "expires_at": utc_now() + TTL}))


async def remote(db, client, query, kind, page, locale):
    path = {"all": "multi", "movie": "movie", "tv": "tv", "person": "person", "company": "company"}[kind]
    response = await client._get(f"/search/{path}", {"query": query, "page": page, "include_adult": False})
    keys = []
    for raw in response.get("results", []):
        item_kind = raw.get("media_type", kind)
        if item_kind in ("movie", "tv"):
            item = catalog_item({**raw, "media_type": item_kind})
            if item:
                store_metadata(db, locale, item)
                keys.append(f"{item_kind}:{item.tmdb_id}")
        elif item_kind in ("person", "company") and raw.get("name"):
            row = entity(db, item_kind, raw["id"], raw["name"])
            reindex(db, row.key)
            keys.append(row.key)
            # TMDB's known_for is a discovery hint, not authoritative role evidence.
            for credit in raw.get("known_for", []):
                item = catalog_item(credit)
                if item:
                    store_metadata(db, locale, item)
    # Multi-search has no companies; merge one company page into each all-domain page.
    total = min(response.get("total_pages", 0), 500)
    if kind == "all":
        companies, company_total = await remote(db, client, query, "company", page, locale)
        keys.extend(companies)
        total = max(total, company_total)
    return list(dict.fromkeys(keys)), total


async def search(db, client, query, locale, kind="all", limit=20, cursor=None, online=False):
    scope = {"query": normalize(query), "locale": locale, "kind": kind, "limit": limit, "online": online}
    if not scope["query"]:
        raise HTTPException(422, "Search query cannot be empty")
    if cursor:
        record = db.get(SearchCache, cursor)
        if not record or record.expires_at <= utc_now():
            raise HTTPException(410, "Search cursor expired; start a new search")
        data = record.data
        if data["scope"] != scope:
            raise HTTPException(422, "Cursor does not belong to this search")
        if "response" in data:
            return data["response"]
        plan = data["plan"]
        cache_key = cursor
    else:
        cache_key = fingerprint(scope)
        record = db.get(SearchCache, cache_key)
        if record and record.expires_at > utc_now():
            return record.data["response"]
        ranked = candidates(db, query, kind)
        # Snapshot display payloads as well as ordering, so enrichment cannot move rows.
        local = [{**display(db, key, locale), "score": score} for key, score in ranked]
        # Prefer an equally relevant title in the requested locale without hiding
        # matches from the other language, original name, aliases or credits.
        local.sort(key=lambda item: (
            -item["score"],
            -(item.get("display_locale") == locale and normalize(item["title"]) == scope["query"]),
            item["key"],
        ))
        plan = {"pending": local, "seen": [r["key"] for r in local], "remote_page": 1 if (online or not local) and len(scope["query"]) >= 3 else None, "query": query}
    pending = list(plan["pending"])
    seen = set(plan["seen"])
    remote_page = plan["remote_page"]
    warning = None
    # At most one upstream page per requested API page; no unbounded gap filling.
    if len(pending) < limit and remote_page:
        try:
            keys, total = await remote(db, client, plan["query"], kind, remote_page, locale)
            for key in keys:
                if key not in seen:
                    pending.append(display(db, key, locale))
                    seen.add(key)
            remote_page = remote_page + 1 if remote_page < total else None
        except TMDBError as exc:
            warning = exc.detail
            # Keep a retry cursor; failed requests are not negative-cached.
    result = pending[:limit]
    pending = pending[limit:]
    next_cursor = None
    if pending or remote_page:
        next_cursor = fingerprint({"parent": cache_key, "scope": scope, "generation": uuid4().hex})
        save(db, next_cursor, {"scope": scope, "plan": {"pending": pending, "seen": sorted(seen), "remote_page": remote_page, "query": plan["query"]}})
    response = {"results": result, "groups": {name: [r for r in result if r["kind"] == name] for name in ("movie", "tv", "person", "company")}, "next_cursor": next_cursor, "warning": warning, "candidate_limit": 600}
    if not warning:
        save(db, cache_key, {"scope": scope, "response": response})
    db.execute(delete(SearchCache).where(SearchCache.expires_at <= utc_now()))
    db.commit()
    return response


async def person_credits(db, client, tmdb_id, locale):
    cache_key = fingerprint({"person": tmdb_id, "locale": locale})
    cached = db.get(SearchCache, cache_key)
    if not cached or cached.expires_at <= utc_now():
        data = await client._get(f"/person/{tmdb_id}", {"append_to_response": "combined_credits"})
        person = entity(db, "person", tmdb_id, data["name"], {"aliases": data.get("also_known_as", [])})
        for group in ("cast", "crew"):
            for raw in data.get("combined_credits", {}).get(group, []):
                item = catalog_item(raw)
                if not item:
                    continue
                store_metadata(db, locale, item)
                key = f"{item.media_type}:{item.tmdb_id}"
                role = "Actor" if group == "cast" else raw.get("job") or "Crew"
                character = raw.get("character") or ""
                if not db.get(CatalogLink, (key, person.key, role, character)):
                    db.add(CatalogLink(media_key=key, entity_key=person.key, role=role, character=character))
                db.flush()
                reindex(db, key)
                from recommendations.features import reindex_features
                reindex_features(db, key)
                db.get(CatalogEntity, key).updated_at = utc_now()
        reindex(db, person.key)
        save(db, cache_key, {"complete": True})
        db.commit()


def surface(db, locale, kind="all", limit=20, cursor=None, profile_id=None, my_list=False, entity_key=None):
    scope = {"locale": locale, "kind": kind, "limit": limit, "profile_id": profile_id, "my_list": my_list, "entity_key": entity_key}
    if cursor:
        record = db.get(SearchCache, cursor)
        if not record or record.expires_at <= utc_now():
            raise HTTPException(410, "Catalog cursor expired")
        if record.data["scope"] != scope:
            raise HTTPException(422, "Cursor does not belong to this catalog query")
        if "response" in record.data:
            return record.data["response"]
        after = record.data["after"]
        ceiling = record.data["ceiling"]
    else:
        after = ""
        ceiling = utc_now().isoformat()
    # Keyset pagination is shared by Home, Movies, Series, My List and credits.
    stmt = select(CatalogEntity.key).where(CatalogEntity.kind.in_(["movie", "tv"]), CatalogEntity.key > after, CatalogEntity.created_at <= datetime.fromisoformat(ceiling))
    if kind != "all":
        stmt = stmt.where(CatalogEntity.kind == kind)
    if my_list:
        stmt = stmt.join(LibraryIntent, (LibraryIntent.tmdb_id == CatalogEntity.tmdb_id) & (LibraryIntent.media_type == CatalogEntity.kind)).where(LibraryIntent.profile_id == profile_id, LibraryIntent.in_my_list.is_(True))
    if entity_key:
        stmt = stmt.where(CatalogEntity.key.in_(select(CatalogLink.media_key).where(CatalogLink.entity_key == entity_key)))
    keys = list(db.scalars(stmt.order_by(CatalogEntity.key).limit(limit + 1)))
    next_cursor = None
    if len(keys) > limit:
        next_cursor = uuid4().hex
        save(db, next_cursor, {"scope": scope, "after": keys[limit - 1], "ceiling": ceiling})
    items = [display(db, key, locale) for key in keys[:limit]]
    if entity_key:
        for item in items:
            item["roles"] = sorted(set(db.scalars(select(CatalogLink.role).where(CatalogLink.entity_key == entity_key, CatalogLink.media_key == item["key"]))))
    response = {"results": items, "next_cursor": next_cursor}
    if cursor:
        save(db, cursor, {"scope": scope, "response": response})
    db.commit()
    return response
