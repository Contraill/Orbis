"""Candidate generation -> scoring -> eligibility -> ranking -> suppression -> diversity."""
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from math import log1p
from typing import Protocol
from sqlalchemy import select, func
from db.models.catalog import CatalogEntity, CatalogFeature
from recommendations.config import POLICY
from recommendations.features import DomainEligibility, domain


@dataclass
class Candidate:
    entity: CatalogEntity
    terms: set = field(default_factory=set)
    sources: set = field(default_factory=set)
    related_to: set = field(default_factory=set)


@dataclass
class Ranked:
    candidate: Candidate
    score: float
    contributions: dict
    exclusion: str | None = None


class CandidateGenerator(Protocol):
    def generate(self, db, taste, kind, baseline_keys): ...


class Recommender(Protocol):
    version: str
    def rank(self, taste, candidates): ...


class LocalCandidates:
    def __init__(self, policy=POLICY):
        self.policy = policy

    def generate(self, db, taste, kind="all", baseline_keys=None):
        sources, related = defaultdict(set), defaultdict(set)
        # Relevance-index lookups, never fuzzy/feature comparisons over the catalog.
        top_terms = sorted(taste.affinities, key=lambda t: (-taste.affinities[t] * self.policy.feature_weights[t.split(":")[0]], t))[:self.policy.feature_query_limit]
        if top_terms:
            query = select(CatalogFeature.media_key, func.count().label("overlap")).join(CatalogEntity, CatalogEntity.key == CatalogFeature.media_key).where(CatalogFeature.term.in_(top_terms))
            if kind != "all":
                query = query.where(CatalogEntity.kind == kind)
            for key, _ in db.execute(query.group_by(CatalogFeature.media_key).order_by(func.count().desc(), CatalogFeature.media_key).limit(self.policy.candidate_limit // 2)):
                sources[key].add("shared_features")
        for seed, _ in taste.sources:
            row = db.get(CatalogEntity, seed)
            for ref in (row.features.get("related", []) if row else [])[:40]:
                key = f"{ref['media_type']}:{ref['tmdb_id']}"
                sources[key].add("tmdb_" + ref.get("relation", "similar"))
                related[key].add(seed)
        for source, keys in (baseline_keys or {}).items():
            for key in keys:
                sources[key].add(source)
                if source.endswith(("/recommendations", "/similar")):
                    bits = source.strip("/").split("/")
                    related[key].add(f"{bits[0]}:{bits[1]}")
        # Local fallback remains useful with missing credentials or no network.
        query = select(CatalogEntity.key).where(CatalogEntity.kind.in_(["movie", "tv"]))
        if kind != "all":
            query = query.where(CatalogEntity.kind == kind)
        for key in db.scalars(query.order_by(CatalogEntity.updated_at.desc(), CatalogEntity.key).limit(100)):
            sources[key].add("local_catalog")
        # Stable source priority keeps baseline/related candidates from crowding out affinity.
        keys = sorted(sources, key=lambda k: (-len(sources[k]), k))[:self.policy.candidate_limit]
        if not keys:
            return []
        features = defaultdict(set)
        for f in db.scalars(select(CatalogFeature).where(CatalogFeature.media_key.in_(keys))):
            features[f.media_key].add(f.term)
        query = select(CatalogEntity).where(CatalogEntity.key.in_(keys), CatalogEntity.kind.in_(["movie", "tv"]))
        if kind != "all":
            query = query.where(CatalogEntity.kind == kind)
        return [Candidate(e, features[e.key] | {f"media:{e.kind}"}, sources[e.key], related[e.key]) for e in db.scalars(query.order_by(CatalogEntity.key))]


class HybridRecommender:
    def __init__(self, policy=POLICY, eligibility=None):
        self.policy = policy
        self.version = policy.version
        self.eligibility = eligibility or DomainEligibility()

    def rank(self, taste, candidates):
        ranked = []
        for c in candidates:
            parts = {}
            for prefix, coefficient in self.policy.feature_weights.items():
                matches = sorted((taste.affinities.get(t, 0) for t in c.terms if t.startswith(prefix + ":")), reverse=True)
                parts[prefix + "_affinity"] = coefficient * sum(matches[:self.policy.feature_match_cap]) / max(1, min(len(matches), self.policy.feature_match_cap))
            parts["onboarding_similarity"] = sum(min(taste.signals[k]["contributions"]["onboarding"], self.policy.onboarding) / self.policy.onboarding for k in c.related_to if k in taste.signals and taste.signals[k]["weight"] > 0)
            parts["engagement_similarity"] = sum(min(taste.signals[k]["weight"], self.policy.related_engagement_cap) / self.policy.related_engagement_cap for k in c.related_to if k in taste.signals and taste.signals[k]["behavioral"])
            parts["popularity"] = min(log1p(max(c.entity.features.get("popularity", 0), 0)) / self.policy.popularity_normalizer, self.policy.popularity_cap)
            signal = taste.signals.get(c.entity.key, {})
            parts["my_list"] = self.policy.list_item_boost if signal.get("contributions", {}).get("my_list") else 0
            parts["stale_penalty"] = -self.policy.stale if signal.get("stale") else 0
            exclusion = self.eligibility.reason(domain(c.entity.features), taste.domains)
            if c.entity.key in taste.excluded:
                exclusion = "not_interested"
            elif c.entity.key in taste.seen:
                exclusion = "seen_or_active_series"
            elif signal.get("contributions", {}).get("onboarding"):
                exclusion = "onboarding_seed"  # seeds are input, not new discoveries
            ranked.append(Ranked(c, round(sum(parts.values()), 6), parts, exclusion))
        return sorted(ranked, key=lambda r: (-r.score, r.candidate.entity.key))


def diversify(ranked, limit, used=(), policy=POLICY):
    """Relevance-bounded deterministic MMR with franchise/person/genre penalties."""
    remaining = [r for r in ranked if not r.exclusion and r.candidate.entity.key not in used]
    selected, counts = [], Counter()
    while remaining and len(selected) < limit:
        best = max(r.score for r in remaining)
        floor = best - max(abs(best) * (1 - policy.diversity_relevance_floor), policy.diversity_absolute_margin)
        pool = [r for r in remaining if r.score >= floor]
        def adjusted(r):
            penalty = sum(counts[t] * (policy.diversity_franchise_penalty if t.startswith("collection:") else policy.diversity_feature_penalty if t.startswith(("genre:", "director:", "creator:", "cast:", "media:")) else 0) for t in r.candidate.terms)
            return (-round(r.score - policy.diversity_strength * penalty, 6), r.candidate.entity.key)
        choice = min(pool, key=adjusted)
        selected.append(choice)
        counts.update(choice.candidate.terms)
        remaining.remove(choice)
    return selected
