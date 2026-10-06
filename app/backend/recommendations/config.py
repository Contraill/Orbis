"""Versioned, centralized v1 policy. Changing weights changes materialization keys."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Policy:
    version: str = "hybrid-v1"
    onboarding: float = 3.0
    completion: float = 5.0
    progression: float = 5.0
    my_list: float = 4.0
    rewatch: float = 3.0
    substantial: float = 1.5
    returns: float = 1.0
    onboarding_decay_titles: int = 12
    recency_floor: float = .4
    max_rewatches: int = 2
    return_days_cap: int = 2
    feature_match_cap: int = 3
    related_engagement_cap: float = 8
    popularity_cap: float = .7
    popularity_normalizer: float = 10
    list_item_boost: float = .4
    diversity_franchise_penalty: float = 2
    diversity_feature_penalty: float = .3
    diversity_absolute_margin: float = .5
    stale: float = 1.5
    substantial_seconds: int = 1200
    episode_seconds: int = 600
    activity_bucket_seconds: int = 600
    stale_days: int = 30
    recency_days: int = 120
    source_limit: int = 12
    progress_limit: int = 1000
    candidate_limit: int = 400
    feature_query_limit: int = 40
    shelf_items: int = 6
    # Safety bound for curated opening rows. Semantic continuation is generated
    # from a bounded candidate snapshot and is not capped by this value.
    max_shelves: int = 96
    feed_minutes: int = 20
    upstream_hours: int = 12
    upstream_budget: int = 10
    upstream_timeout: float = 3.0
    diversity_strength: float = 0.8
    diversity_relevance_floor: float = 0.65
    feature_weights: dict[str, float] = field(default_factory=lambda: {
        "genre": 2.0, "keyword": 3.0, "cast": 1.2, "director": 2.5,
        "creator": 2.5, "producer": .6, "company": .5,
    })


POLICY = Policy()
