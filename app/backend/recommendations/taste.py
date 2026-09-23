"""Bounded evidence aggregation; save counts and provider data are never inputs."""
from collections import defaultdict
from dataclasses import dataclass, field
from math import exp
from sqlalchemy import select, func, cast, Integer, case
from db.models.foundation import ViewingProgress, ViewingDay, LibraryIntent
from db.models.catalog import CatalogEntity, CatalogFeature
from db.models.profile import utc_now
from metadata.search import fingerprint
from recommendations.config import POLICY
from recommendations.features import domain


@dataclass
class Taste:
    signals: dict = field(default_factory=dict)
    affinities: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    excluded: set = field(default_factory=set)
    seen: set = field(default_factory=set)
    domains: set = field(default_factory=set)
    personalized: bool = False


def signal_signature(db, profile, policy=POLICY):
    """Cheap indexed profile aggregates, not a complete taste-model rebuild."""
    p, d = ViewingProgress, ViewingDay
    bucket = policy.activity_bucket_seconds
    progress = db.execute(select(
        func.coalesce(func.sum(cast(p.watched_seconds / bucket, Integer)), 0),
        func.coalesce(func.sum(p.completions), 0), func.coalesce(func.sum(p.rewatches), 0),
        func.max(case((p.watched_seconds >= bucket, func.date(p.last_watched_at)))),
    ).where(p.profile_id == profile.id)).one()
    days = db.execute(select(
        func.coalesce(func.sum(case((d.watched_seconds >= policy.episode_seconds, 1), else_=0)), 0),
        func.coalesce(func.sum(case((d.watched_seconds >= policy.episode_seconds, func.min(d.visits, 3)), else_=0)), 0),
    ).where(d.profile_id == profile.id)).one()
    intents = [(i.media_type, i.tmdb_id, i.in_my_list, i.not_interested,
                i.hidden_at.isoformat() if i.hidden_at else None) for i in db.scalars(
        select(LibraryIntent).where(LibraryIntent.profile_id == profile.id).order_by(LibraryIntent.media_type, LibraryIntent.tmdb_id))]
    return fingerprint({"profile": profile.id, "seeds": profile.onboarding_seeds, "progress": list(progress),
        "days": list(days), "intents": intents, "day": utc_now().date().isoformat()})


def build_taste(db, profile, policy=POLICY, now=None):
    now = now or utc_now()
    taste = Taste()
    recent = select(ViewingProgress).where(ViewingProgress.profile_id == profile.id).order_by(
        ViewingProgress.last_watched_at.desc(), ViewingProgress.content_key).limit(policy.progress_limit)
    rows = db.scalars(recent).all()
    subquery = select(ViewingProgress.content_key).where(ViewingProgress.profile_id == profile.id).order_by(
        ViewingProgress.last_watched_at.desc(), ViewingProgress.content_key).limit(policy.progress_limit)
    days = defaultdict(list)
    for day in db.scalars(select(ViewingDay).where(ViewingDay.profile_id == profile.id, ViewingDay.content_key.in_(subquery))):
        if day.watched_seconds >= policy.episode_seconds:
            days[day.content_key].append(day)
    grouped = {}
    def item(key):
        return grouped.setdefault(key, {"seconds": 0, "completions": 0, "rewatches": 0,
            "episodes": 0, "days": set(), "visits": 0, "last": None, "onboarding": False, "my_list": False})
    for p in rows:
        s = item(f"{p.media_type}:{p.tmdb_id}")
        s["seconds"] += p.watched_seconds
        s["completions"] += p.completions
        s["rewatches"] += p.rewatches
        s["episodes"] += int(p.media_type == "tv" and p.watched_seconds >= policy.episode_seconds)
        if p.watched_seconds >= policy.episode_seconds:
            s["last"] = max(s["last"], p.last_watched_at) if s["last"] else p.last_watched_at
        s["days"].update(d.day for d in days[p.content_key])
        s["visits"] += sum(min(d.visits, 3) for d in days[p.content_key])
        # Brief abandoned starts receive only a title penalty, never positive affinity.
        if not s["last"]:
            s["brief_last"] = p.last_watched_at
    for seed in profile.onboarding_seeds[:5]:
        item(f"{seed['media_type']}:{seed['tmdb_id']}")["onboarding"] = True
    for intent in db.scalars(select(LibraryIntent).where(LibraryIntent.profile_id == profile.id)):
        key = f"{intent.media_type}:{intent.tmdb_id}"
        item(key)["my_list"] = intent.in_my_list
        if intent.not_interested:
            taste.excluded.add(key)
    keys = list(grouped)
    entities = {e.key: e for e in db.scalars(select(CatalogEntity).where(CatalogEntity.key.in_(keys)))} if keys else {}
    terms = defaultdict(set)
    if keys:
        for row in db.scalars(select(CatalogFeature).where(CatalogFeature.media_key.in_(keys))):
            terms[row.media_key].add(row.term)
    behavior_count = sum(1 for key, s in grouped.items() if key not in taste.excluded and
                         (s["completions"] or s["rewatches"] or (s["episodes"] >= 2 and len(s["days"]) >= 2)))
    onboarding_scale = 1 / (1 + behavior_count / policy.onboarding_decay_titles)  # gradual, never erased by one start
    affinity = defaultdict(float)
    total_positive = 0
    for key, s in grouped.items():
        row = entities.get(key)
        kind = key.split(":")[0]
        runtime = ((row.features.get("runtime_minutes") or 0) * 60) if row else 0
        high_completion = bool(s["completions"] or (kind == "movie" and runtime and s["seconds"] >= runtime * .8))
        progression = s["episodes"] >= 2 and len(s["days"]) >= 2
        last = s["last"] or s.get("brief_last")
        age = max(0, (now - last).total_seconds() / 86400) if last else 0
        recency = policy.recency_floor + (1 - policy.recency_floor) * exp(-age / policy.recency_days)
        parts = {
            "onboarding": policy.onboarding * onboarding_scale if s["onboarding"] else 0,
            "completion": policy.completion if high_completion else 0,
            "progression": policy.progression if progression else 0,
            "my_list": policy.my_list if s["my_list"] else 0,
            "rewatch": policy.rewatch * min(s["rewatches"], policy.max_rewatches),
            "substantial_viewing": policy.substantial if s["seconds"] >= policy.substantial_seconds and not high_completion else 0,
            "return_frequency": policy.returns * min(max(len(s["days"]) - 1, 0), policy.return_days_cap) if s["seconds"] >= policy.substantial_seconds else 0,
        }
        behavioral = sum(parts[n] for n in ("completion", "progression", "rewatch", "substantial_viewing", "return_frequency"))
        parts["recency_adjustment"] = behavioral * (recency - 1)
        stale = bool(last and age >= policy.stale_days and not high_completion and not progression)
        parts["stale_penalty"] = -policy.stale if stale else 0
        weight = max(0, sum(parts.values())) if key not in taste.excluded else 0
        if kind == "movie" and high_completion:
            taste.seen.add(key)
        if kind == "tv" and (progression or high_completion or (s["episodes"] and age < policy.stale_days)):
            taste.seen.add(key)
        meaningful_domain_interest = s["onboarding"] or s["my_list"] or high_completion or progression or s["rewatches"] or s["seconds"] >= policy.substantial_seconds
        if row and key not in taste.excluded and domain(row.features) == "anime" and meaningful_domain_interest:
            taste.domains.add("anime")
        taste.signals[key] = {"weight": round(weight, 5), "contributions": parts,
            "stale": stale, "watched_seconds": s["seconds"], "active_days": len(s["days"]),
            "meaningful_episodes": s["episodes"], "seen": key in taste.seen,
            "excluded": key in taste.excluded, "behavioral": behavioral > 0}
        if weight and row:
            total_positive += weight
            for term in terms[key]:
                if term.split(":")[0] in policy.feature_weights:
                    affinity[term] += weight
            taste.sources.append((key, weight))
    taste.affinities = {term: weight / max(total_positive, 1) for term, weight in affinity.items()}
    taste.sources = sorted(taste.sources, key=lambda v: (-v[1], v[0]))[:policy.source_limit]
    taste.personalized = bool(taste.affinities)
    return taste


def suppress_consumed(db, profile, taste, candidates, policy=POLICY):
    """All-history seen lookup, bounded by candidate identities rather than taste window."""
    from sqlalchemy import tuple_
    if not candidates:
        return
    entities = {(c.entity.kind, c.entity.tmdb_id): c.entity for c in candidates}
    p = ViewingProgress
    query = select(p.media_type, p.tmdb_id, func.sum(p.completions), func.sum(p.watched_seconds),
        func.sum(case((p.watched_seconds >= policy.episode_seconds, 1), else_=0)),
        func.max(case((p.watched_seconds >= policy.episode_seconds, p.last_watched_at)))).where(
        p.profile_id == profile.id, tuple_(p.media_type, p.tmdb_id).in_(list(entities))).group_by(p.media_type, p.tmdb_id)
    from datetime import timedelta
    for kind, tmdb_id, completions, seconds, episodes, last in db.execute(query):
        entity = entities[(kind, tmdb_id)]
        runtime = (entity.features.get("runtime_minutes") or 0) * 60
        movie_seen = kind == "movie" and (completions or (runtime and seconds >= runtime * .8))
        tv_seen = kind == "tv" and (completions or episodes >= 2 or (episodes and last and last >= utc_now() - timedelta(days=policy.stale_days)))
        if movie_seen or tv_seen:
            taste.seen.add(entity.key)
