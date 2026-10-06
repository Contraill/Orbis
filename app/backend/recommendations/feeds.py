"""Materialized shelf feeds, independent of the replaceable ranking implementation."""
from dataclasses import asdict
from datetime import timedelta
from sqlalchemy import select, func, delete
from fastapi import HTTPException
from db.models.catalog import CatalogEntity, CatalogSeason, SearchCache
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
    from core.maintenance import trim_cache
    trim_cache(db,key)


def localized(profile, en, tr):
    return tr if profile.locale == "tr-TR" else en


def assemble(db, profile, surface, taste, ranked, policy, display_items):
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
    def add(shelf_id, title, options, personalized=False, count=None, context_key=None, seasons=None):
        if len(shelves) >= policy.max_shelves:
            return 0
        picked = diversify(options, count or policy.shelf_items, used, policy)
        if not picked:
            return 0
        items = [dict(display_items[r.candidate.entity.key]) for r in picked]
        if seasons:
            for item in items:
                item["new_season"] = seasons[item["key"]]
        used.update(r.candidate.entity.key for r in picked)
        shelves.append({"id": shelf_id, "kind": shelf_id.split(":")[0], "title": title,
            "personalized": personalized, "context_key": context_key, "items": items})
        return len(picked)
    add("hero", localized(profile, "Featured", "Öne çıkan"), ranked, taste.personalized, 1)
    if continue_items:
        shelves.append({"id": "continue", "kind": "continue", "title": localized(profile, "Continue Watching", "İzlemeye Devam Et"),
            "personalized": False, "items": continue_items, "context_key": None})
    eligible = [r for r in ranked if not r.exclusion]
    today = utc_now().date()
    if surface != "movies":
        from datetime import timedelta
        cutoff = (today - timedelta(days=180)).isoformat()
        tv_keys = [r.candidate.entity.key for r in eligible if r.candidate.entity.kind == "tv"]
        seasons = {}
        if tv_keys:
            rows = db.execute(select(CatalogSeason.series_key, CatalogSeason.season_number, CatalogSeason.air_date)
                .where(CatalogSeason.series_key.in_(tv_keys), CatalogSeason.season_number > 1,
                    CatalogSeason.air_date >= cutoff, CatalogSeason.air_date <= today.isoformat())
                .order_by(CatalogSeason.air_date.desc(), CatalogSeason.series_key).limit(100))
            for key, number, air_date in rows:
                if key not in seasons:
                    seasons[key] = number
        season_ranked = [r for r in eligible if r.candidate.entity.key in seasons]
        add("new-seasons", localized(profile, "New Seasons", "Yeni sezonu çıkan diziler"), season_ranked,
            count=policy.shelf_items, seasons=seasons)
    from datetime import date
    def age(row):
        value = display_items[row.candidate.entity.key].get("release_date")
        try:
            days = (today - date.fromisoformat(value)).days
        except (TypeError, ValueError):
            return None
        return days if 0 <= days <= 180 else None
    releases = [Ranked(r.candidate, 180 - age(r), r.contributions, r.exclusion)
        for r in eligible if age(r) is not None]
    releases.sort(key=lambda r: (-r.score, r.candidate.entity.key))
    add("new-releases", localized(profile,
        {"home": "New Movies & Series", "movies": "New Movies", "series": "New Series"}[surface],
        {"home": "Yeni filmler ve diziler", "movies": "Yeni filmler", "series": "Yeni diziler"}[surface]), releases)
    popular = [r for r in eligible if any("/trending/" in source or source.endswith("/popular") for source in r.candidate.sources)]
    if not popular:
        popular = eligible
    popular = [Ranked(r.candidate, float(r.candidate.entity.features.get("popularity") or 0), r.contributions, r.exclusion)
        for r in popular]
    popular.sort(key=lambda r: (-r.score, r.candidate.entity.key))
    add("popular-now", localized(profile,
        {"home": "Popular Right Now", "movies": "Popular Movies", "series": "Popular Series"}[surface],
        {"home": "Şu anda popüler", "movies": "Popüler filmler", "series": "Popüler diziler"}[surface]), popular)
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
    return shelves


def semantic_templates(db, profile, surface, taste, ranked, reserved=()):
    """Bounded, real catalog dimensions; genres precede narrower relationships."""
    from collections import defaultdict
    from metadata.genres import NAMES, PAIRS, label

    scope = {"home": "all", "movies": "movie", "series": "tv"}[surface]
    eligible = [r for r in ranked if not r.exclusion and r.candidate.entity.key not in reserved]
    by_term = defaultdict(list)
    for row in eligible:
        for term in row.candidate.terms:
            if term.startswith(("genre:", "keyword:", "cast:", "director:", "creator:", "producer:", "company:")):
                by_term[term].append(row.candidate.entity.key)
    templates = []
    seen_genres = set()
    for term, keys in by_term.items():
        if not term.startswith("genre:"):
            continue
        genre_id = int(term.split(":", 1)[1])
        if genre_id not in NAMES:
            continue
        canonical = next((movie for movie, tv in PAIRS.items() if tv == genre_id), genre_id) if scope == "all" else genre_id
        if canonical in seen_genres:
            continue
        seen_genres.add(canonical)
        members = set(keys)
        if scope == "all" and canonical in PAIRS:
            members.update(by_term.get(f"genre:{PAIRS[canonical]}", []))
        ordered = [r.candidate.entity.key for r in eligible if r.candidate.entity.key in members]
        if len(ordered) >= 2:
            templates.append({"signature": f"genre:{canonical}", "title": label(canonical, scope, profile.locale),
                "genre_id": canonical, "genre_scope": scope, "keys": ordered,
                "priority": taste.affinities.get(term, 0)})
    templates.sort(key=lambda row: (-row["priority"], -len(row["keys"]), row["signature"]))
    # TMDB keyword names are usually English even in tr-TR metadata. Only
    # emit Turkish keyword headings when a reviewed localized label exists.
    keyword_tr = {
        "absurd": "absürt mizah", "adult animation": "yetişkin animasyonu",
        "artificial intelligence (a.i.)": "yapay zekâ", "based on comic": "çizgi romandan uyarlama",
        "based on novel or book": "romandan veya kitaptan uyarlama", "buddy cop": "polis ortaklığı",
        "detective": "dedektif", "family": "aile", "father daughter relationship": "baba-kız ilişkisi",
        "friendship": "dostluk", "investigation": "soruşturma", "judge": "hâkim",
        "miami, florida": "Miami", "motorcycle": "motosiklet", "murder": "cinayet",
        "new york city": "New York", "parody": "parodi", "police": "polis",
        "revenge": "intikam", "romance": "aşk", "satire": "hiciv", "sequel": "devam hikâyesi",
        "sitcom": "durum komedisi", "small town": "küçük kasaba",
        "super power": "süper güç", "superhero": "süper kahraman", "time travel": "zaman yolculuğu",
    }
    for term, keys in sorted(by_term.items()):
        prefix, identifier = term.split(":", 1)
        if prefix == "genre" or len(keys) < 3:
            continue
        if prefix == "keyword":
            name = next((ref.get("name") for r in eligible for ref in r.candidate.entity.features.get("keywords", [])
                if str(ref.get("tmdb_id")) == identifier and ref.get("name")), None)
            if name and profile.locale == "tr-TR":
                name = keyword_tr.get(name.casefold())
            heading = localized(profile, "Stories about ", "Teması: ")
        else:
            entity = db.get(CatalogEntity, f"{'company' if prefix == 'company' else 'person'}:{identifier}")
            name = entity.name if entity else None
            heading = localized(profile, {
                "cast": "Featuring ", "director": "Directed by ", "creator": "Created by ",
                "producer": "Produced by ", "company": "From "}[prefix], {
                "cast": "Oyuncu: ", "director": "Yönetmen: ", "creator": "Yaratıcı: ",
                "producer": "Yapımcı: ", "company": "Yapım şirketi: "}[prefix])
        if name:
            templates.append({"signature": term, "title": heading + name, "keys": keys,
                "priority": taste.affinities.get(term, 0)})
    return templates


def next_shelves(data, state, batch_size):
    """Replayable bounded continuation with recent-shelf and recent-card windows."""
    curated = data["shelves"]
    templates = data["templates"]
    items = data["items"]
    output = []
    state = dict(state)
    recent_shelves = list(state.get("recent_shelves", []))
    recent_items = list(state.get("recent_items", []))
    while len(output) < batch_size and state["offset"] < len(curated):
        row = curated[state["offset"]]
        output.append(row)
        recent_items.extend(item["key"] for item in row["items"])
        state["offset"] += 1
    # At most two rotations are searched per shelf; a tiny catalog can recycle
    # earlier, but a healthy catalog avoids adjacent signatures and cards.
    while len(output) < batch_size and templates:
        choice = None
        fallback = None
        for advance in range(len(templates) * 2):
            index = (state["template_index"] + advance) % len(templates)
            candidate = templates[index]
            if candidate["signature"] in recent_shelves and advance < len(templates):
                continue
            fresh_count = sum(key not in recent_items for key in candidate["keys"])
            if fallback is None:
                fallback = (candidate, index)
            if fresh_count >= 2:
                choice = (candidate, index)
                break
        if choice is None:
            choice = fallback
        if choice is None:
            break
        template, index = choice
        state["template_index"] = index + 1
        ordered = template["keys"]
        offset = (state["serial"] * 3) % len(ordered)
        rotated = ordered[offset:] + ordered[:offset]
        fresh = [key for key in rotated if key not in recent_items]
        chosen = (fresh if len(fresh) >= 2 else fresh + [key for key in rotated if key not in fresh])[:min(6, len(ordered))]
        signature = template["signature"]
        output.append({"id": f"semantic:{signature}:{state['serial']}", "kind": "genre" if template.get("genre_id") else "theme",
            "title": template["title"], "personalized": data["personalized"],
            "context_key": None, "genre_id": template.get("genre_id"), "genre_scope": template.get("genre_scope"),
            "items": [items[key] for key in chosen]})
        state["serial"] += 1
        recent_shelves = (recent_shelves + [signature])[-min(12, max(1, len(templates) - 1)):]
        recent_items = (recent_items + chosen)[-48:]
    state["recent_shelves"] = recent_shelves
    state["recent_items"] = recent_items
    return output, state


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
        snapshot_id, state = pointer.data["snapshot_id"], pointer.data["state"]
        snapshot = db.get(SearchCache, snapshot_id)
        if not snapshot or snapshot.expires_at <= utc_now():
            raise HTTPException(410, "Feed snapshot expired; restart the feed")
        if snapshot.data["signature"] != signature:
            raise HTTPException(409, "Profile activity changed; restart the feed")
    else:
        root = fingerprint({"feed": scope, "signals": signature, "catalog": current_catalog_signature(db), "engine": engine.version, "policy": asdict(policy), "discovery": 4})
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
            display_items = {r.candidate.entity.key: display(db, r.candidate.entity.key, profile.locale)
                for r in ranked if not r.exclusion}
            curated = assemble(db, profile, surface, taste, ranked, policy, display_items)
            reserved = {item["key"] for shelf in curated for item in shelf["items"]}
            continued_keys = {f"{item['media_type']}:{item['tmdb_id']}" for item in continue_watching(db, profile, kind)}
            reserved.update(continued_keys)
            templates = semantic_templates(db, profile, surface, taste, ranked, reserved)
            if not templates:
                # A small catalog can have all eligible titles in the opening
                # shelves. Reuse its real dimensions, but never active viewing.
                templates = semantic_templates(db, profile, surface, taste, ranked, continued_keys)
            data = {"type": "feed_snapshot", "scope": scope, "signature": signature,
                "personalized": taste.personalized, "shelves": curated,
                "templates": templates, "items": display_items,
                "warnings": warnings, "diagnostics": {"engine": engine.version, "enabled_domains": sorted(taste.domains),
                    "source_signals": taste.signals, "affinities": taste.affinities,
                    "candidates": [{"key": r.candidate.entity.key, "score": r.score, "contributions": r.contributions,
                        "sources": sorted(r.candidate.sources), "exclusion": r.exclusion} for r in ranked]}}
            # Materialization key reflects the catalog after warming, not before it.
            root = fingerprint({"feed": scope, "signals": signature, "catalog": current_catalog_signature(db), "engine": engine.version, "policy": asdict(policy), "discovery": 4})
            put(db, root, data, policy)
            snapshot = db.get(SearchCache, root)
        snapshot_id, state = root, {"offset": 0, "template_index": 0, "serial": 0, "recent_shelves": [], "recent_items": []}
    data = snapshot.data
    # Active scrolling renews the bounded materialization lease; idle cursors
    # still expire, and profile activity invalidates the snapshot as before.
    snapshot.expires_at = utc_now() + timedelta(minutes=policy.feed_minutes)
    if cursor:
        pointer.expires_at = snapshot.expires_at
    shelves, next_state = next_shelves(data, state, batch_size)
    next_cursor = None
    if next_state["offset"] < len(data["shelves"]) or data["templates"]:
        next_cursor = fingerprint({"feed_snapshot": snapshot_id, "offset": next_state["offset"], "serial": next_state["serial"]})
        if not db.get(SearchCache, next_cursor):
            put(db, next_cursor, {"type": "feed_cursor", "scope": scope, "snapshot_id": snapshot_id, "state": next_state}, policy)
    db.execute(delete(SearchCache).where(SearchCache.expires_at <= utc_now()))
    db.commit()
    return {"snapshot_id": snapshot_id, "surface": surface, "personalized": data["personalized"],
        "shelves": shelves, "next_cursor": next_cursor, "warnings": data["warnings"]}
