import asyncio
import unittest
from datetime import timedelta
from dataclasses import replace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from db.base import Base
import db.models
from db.models.catalog import CatalogEntity, CatalogFeature, SearchCache
from db.models.foundation import ViewingProgress, ViewingDay, LibraryIntent
from db.models.profile import Profile, utc_now
from db.models.playback import PlaybackState
from metadata.schemas import CatalogDetails
from metadata.localization import store_metadata
from recommendations.config import POLICY
from recommendations.features import domain
from recommendations.taste import build_taste, signal_signature
from recommendations.engine import HybridRecommender, LocalCandidates, diversify
from recommendations.feeds import feed
from recommendations.enrichment import warm


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.profile = Profile(name="One", onboarding_seeds=[])
        self.other = Profile(name="Two", onboarding_seeds=[])
        self.db.add_all([self.profile, self.other])
        self.db.commit()
        self.now = utc_now()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def put(self, identifier, kind="movie", genre=878, anime=False, **extra):
        data = dict(tmdb_id=identifier, media_type=kind, title=f"Title {identifier}", original_title=f"Title {identifier}",
            genre_refs=[{"tmdb_id": 16 if anime else genre, "name": "Animation" if anime else "Science Fiction"}],
            original_language="ja" if anime else "en", countries=["JP" if anime else "US"], runtime_minutes=100,
            popularity=20, keywords=[{"tmdb_id": 5, "name": "space"}])
        data.update(extra)
        store_metadata(self.db, "en-US", CatalogDetails(**data))
        self.db.commit()
        return f"{kind}:{identifier}"

    def seed(self, *keys, profile=None):
        owner = profile or self.profile
        owner.onboarding_seeds = [{"media_type": k.split(":")[0], "tmdb_id": int(k.split(":")[1])} for k in keys]
        self.db.commit()

    def progress(self, key, seconds=30, completions=0, rewatches=0, episode=None, days_ago=0):
        kind, tmdb_id = key.split(":")
        content_key = key if episode is None else f"{key}:s1:e{episode}"
        last = self.now - timedelta(days=days_ago)
        p = ViewingProgress(profile_id=self.profile.id, content_key=content_key, media_type=kind, tmdb_id=int(tmdb_id),
            season_number=1 if episode else None, episode_number=episode, started_at=last, last_watched_at=last,
            sampled_at=last, last_position=seconds, watched_seconds=seconds, cycle_seconds=seconds,
            completions=completions, rewatches=rewatches, cycle_completed=bool(completions))
        self.db.add(p)
        self.db.add(ViewingDay(profile_id=self.profile.id, content_key=content_key, day=last.date().isoformat(), watched_seconds=seconds, visits=1, completions=completions))
        self.db.commit()
        return p

    def intent(self, key, listed=False, negative=False):
        kind, tmdb_id = key.split(":")
        row = self.db.get(LibraryIntent, (self.profile.id, kind, int(tmdb_id)))
        if row is None:
            row = LibraryIntent(profile_id=self.profile.id, media_type=kind, tmdb_id=int(tmdb_id))
            self.db.add(row)
        row.in_my_list, row.not_interested = listed, negative
        self.db.commit()

    def rank(self, profile=None):
        taste = build_taste(self.db, profile or self.profile)
        return taste, HybridRecommender().rank(taste, LocalCandidates().generate(self.db, taste))

    def page(self, **kw):
        return asyncio.run(feed(self.db, kw.pop("profile", self.profile), enrich=False, **kw))

    def test_cold_start_five_selections_and_zero(self):
        keys = [self.put(n) for n in range(1, 7)]
        empty, ranked = self.rank()
        self.assertFalse(empty.personalized)
        self.assertTrue(ranked)
        self.seed(*keys[:5])
        taste, ranked = self.rank()
        self.assertEqual(len(taste.sources), 5)
        self.assertTrue(taste.personalized)
        self.assertEqual([r.candidate.entity.key for r in ranked if not r.exclusion], [keys[-1]])
        self.assertGreater(taste.signals[keys[0]]["contributions"]["onboarding"], 0)

    def test_completion_brief_start_stale_rewatch_and_substantial(self):
        for n in range(1, 6):
            self.put(n)
        self.progress("movie:1", 5400, completions=1, rewatches=1)
        self.progress("movie:2", 20)
        self.progress("movie:3", 400, days_ago=40)
        self.progress("movie:4", 2400)
        taste, ranked = self.rank()
        self.assertGreater(taste.signals["movie:1"]["contributions"]["completion"], 0)
        self.assertGreater(taste.signals["movie:1"]["contributions"]["rewatch"], 0)
        self.assertEqual(taste.signals["movie:2"]["weight"], 0)
        self.assertLess(taste.signals["movie:3"]["contributions"]["stale_penalty"], 0)
        self.assertGreater(taste.signals["movie:4"]["weight"], 0)
        self.assertEqual(next(r for r in ranked if r.candidate.entity.key == "movie:1").exclusion, "seen_or_active_series")
        self.assertIsNone(next(r for r in ranked if r.candidate.entity.key == "movie:3").exclusion)

    def test_weekly_series_progression_is_canonical_and_meaningful(self):
        self.put(1, "tv")
        self.put(2, "tv")
        self.progress("tv:1", 1500, episode=1, days_ago=14)
        self.progress("tv:1", 1600, episode=2, days_ago=7)
        self.progress("tv:1", 1500, episode=3)
        taste, ranked = self.rank()
        self.assertEqual(taste.signals["tv:1"]["active_days"], 3)
        self.assertEqual(taste.signals["tv:1"]["meaningful_episodes"], 3)
        self.assertGreater(taste.signals["tv:1"]["contributions"]["progression"], 0)
        self.assertEqual(len([r for r in ranked if r.candidate.entity.key == "tv:1"]), 1)
        self.assertIn("tv:1", taste.seen)

    def test_my_list_negative_profile_isolation_and_locale_independence(self):
        self.put(1)
        self.put(2, genre=35, keywords=[])
        self.intent("movie:1", listed=True)
        self.intent("movie:2", negative=True)
        taste, ranked = self.rank()
        other, _ = self.rank(self.other)
        self.assertGreater(taste.signals["movie:1"]["contributions"]["my_list"], 0)
        self.assertFalse(other.personalized)
        self.assertIn("movie:2", taste.excluded)
        self.assertEqual(next(r for r in ranked if r.candidate.entity.key == "movie:2").exclusion, "not_interested")
        self.profile.locale = "tr-TR"
        self.db.commit()
        translated, translated_ranked = self.rank()
        self.assertEqual(taste.affinities, translated.affinities)
        self.assertEqual([(r.candidate.entity.key, r.score) for r in ranked], [(r.candidate.entity.key, r.score) for r in translated_ranked])

    def test_anime_gate_and_generic_animation(self):
        self.put(1, anime=True)
        self.put(2, anime=True)
        self.put(3, genre=16)
        _, ranked = self.rank()
        self.assertEqual(next(r for r in ranked if r.candidate.entity.key == "movie:1").exclusion, "anime_interest_required")
        self.assertIsNone(next(r for r in ranked if r.candidate.entity.key == "movie:3").exclusion)
        self.seed("movie:1")
        taste, ranked = self.rank()
        self.assertIn("anime", taste.domains)
        self.assertIsNone(next(r for r in ranked if r.candidate.entity.key == "movie:2").exclusion)
        self.assertEqual(domain({"genre_refs": [{"tmdb_id": 16}]}), "unknown_animation")
        self.assertEqual(domain({"genre_refs": [{"tmdb_id": 18}], "original_language": "ja"}), "general")

    def test_anime_interest_from_list_and_meaningful_viewing_not_brief_start(self):
        self.put(1, anime=True)
        p = self.progress("movie:1", 30)
        self.assertNotIn("anime", self.rank()[0].domains)
        p.watched_seconds = 1800
        self.db.commit()
        self.assertIn("anime", self.rank()[0].domains)
        p.watched_seconds = 30
        self.intent("movie:1", listed=True)
        self.assertIn("anime", self.rank()[0].domains)
        self.intent("movie:1", listed=True, negative=True)
        self.assertNotIn("anime", self.rank()[0].domains)

    def test_deterministic_diversity_and_deduplication(self):
        for n in range(1, 7):
            self.put(n, collection_id=10 if n < 5 else 20, popularity=20)
        self.seed("movie:1")
        _, ranked = self.rank()
        picked = diversify(ranked, 4)
        self.assertEqual([r.candidate.entity.key for r in picked], [r.candidate.entity.key for r in diversify(ranked, 4)])
        self.assertEqual(picked[0].candidate.entity.features["collection_id"], 10)
        self.assertEqual(picked[1].candidate.entity.features["collection_id"], 20)
        self.assertEqual(len({r.candidate.entity.key for r in picked}), 4)

    def test_feed_scope_continuation_replay_and_no_duplicates(self):
        for n in range(1, 40):
            self.put(n, "movie" if n % 2 else "tv", genre=878 if n % 3 else 35)
        self.seed("movie:1")
        for surface, expected in [("home", {"movie", "tv"}), ("movies", {"movie"}), ("series", {"tv"})]:
            result = self.page(surface=surface, batch_size=1)
            shelves, keys, kinds = [], [], set()
            while True:
                for shelf in result["shelves"]:
                    shelves.append(shelf["id"])
                    for item in shelf["items"]:
                        keys.append(item["key"])
                        kinds.add(item["kind"])
                cursor = result["next_cursor"]
                if not cursor:
                    break
                result = self.page(surface=surface, batch_size=1, cursor=cursor)
                self.assertEqual(result, self.page(surface=surface, batch_size=1, cursor=cursor))
            self.assertEqual(kinds, expected)
            self.assertEqual(len(shelves), len(set(shelves)))
            self.assertEqual(len(keys), len(set(keys)))

    def test_continuation_does_not_rebuild_and_feedback_invalidates(self):
        for n in range(1, 20):
            self.put(n)
        self.seed("movie:1")
        first = self.page(batch_size=1)
        with patch("recommendations.feeds.build_taste", side_effect=AssertionError("Unexpected rebuild")), patch("recommendations.feeds.warm", side_effect=AssertionError("Unexpected upstream")):
            self.page(batch_size=1, cursor=first["next_cursor"])
            self.assertEqual(first, self.page(batch_size=1))
        self.intent("movie:3", negative=True)
        with self.assertRaises(HTTPException) as caught:
            self.page(batch_size=1, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 409)
        new = self.page(batch_size=1)
        self.assertNotEqual(first["snapshot_id"], new["snapshot_id"])
        snapshot = self.db.get(SearchCache, new["snapshot_id"])
        self.assertNotIn("movie:3", [i["key"] for s in snapshot.data["shelves"] for i in s["items"]])

    def test_signature_ignores_save_frequency_but_reacts_to_meaningful_signals(self):
        self.put(1)
        before = signal_signature(self.db, self.profile)
        p = self.progress("movie:1", 20)
        self.assertEqual(before, signal_signature(self.db, self.profile))
        p.sampled_at = utc_now() + timedelta(seconds=30)
        p.watched_seconds = 40
        self.db.commit()
        self.assertEqual(before, signal_signature(self.db, self.profile))
        p.watched_seconds = 1200
        self.db.commit()
        after = signal_signature(self.db, self.profile)
        self.assertNotEqual(before, after)
        p.completions = 1
        self.db.commit()
        self.assertNotEqual(after, signal_signature(self.db, self.profile))
        after = signal_signature(self.db, self.profile)
        self.seed("movie:1")
        self.assertNotEqual(after, signal_signature(self.db, self.profile))

    def test_continue_watching_scope_and_discovery_exclusion(self):
        for kind in ("movie", "tv"):
            self.put(1, kind)
            self.db.add(PlaybackState(profile_id=self.profile.id, content_key=f"{kind}:1" if kind == "movie" else "tv:1:s1:e1", media_type=kind, tmdb_id=1,
                season_number=1 if kind == "tv" else None, episode_number=1 if kind == "tv" else None, position_seconds=600, completed=False, subtitles_enabled=False))
        self.db.commit()
        for surface, kinds in [("home", {"movie", "tv"}), ("movies", {"movie"}), ("series", {"tv"})]:
            page = self.page(surface=surface, batch_size=5)
            shelf = next(s for s in page["shelves"] if s["id"] == "continue")
            self.assertEqual({i["kind"] for i in shelf["items"]}, kinds)
            self.assertFalse(any(i["tmdb_id"] == 1 for s in page["shelves"] if s["id"] != "continue" for i in s["items"]))

    def test_cursor_profile_locale_scope_expiry(self):
        for n in range(1, 15):
            self.put(n)
        first = self.page(batch_size=1)
        with self.assertRaises(HTTPException) as caught:
            self.page(profile=self.other, batch_size=1, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 422)
        self.profile.locale = "tr-TR"
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.page(batch_size=1, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 422)
        self.db.get(SearchCache, first["next_cursor"]).expires_at = self.now - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.page(batch_size=1, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 410)

    def test_cached_bounded_upstream_and_local_failure(self):
        self.put(1)
        client = AsyncMock()
        client._get.return_value = {"results": [{"id": 10, "title": "Remote", "name": "Remote", "genre_ids": [878], "original_language": "en"}]}
        taste = build_taste(self.db, self.profile)
        first = asyncio.run(warm(self.db, self.profile, taste, client=client))
        second = asyncio.run(warm(self.db, self.profile, taste, client=client))
        self.assertEqual(first, second)
        self.assertEqual(client._get.await_count, 4)
        self.assertTrue(self.db.get(CatalogEntity, "movie:10"))
        plan = self.db.execute(text("EXPLAIN QUERY PLAN SELECT media_key FROM catalog_features WHERE term='genre:878'")).all()
        self.assertIn("INDEX", str(plan))

    def test_five_seeds_are_not_discarded_after_first_playback(self):
        for n in range(1, 7):
            self.put(n)
        self.seed(*[f"movie:{n}" for n in range(1, 6)])
        before = build_taste(self.db, self.profile)
        self.progress("movie:6", 20)
        after = build_taste(self.db, self.profile)
        self.assertEqual(before.affinities, after.affinities)
        self.assertEqual(before.sources, after.sources)

    def test_upstream_seed_recommendations_persist_and_are_budgeted(self):
        self.put(1, related=[{"media_type": "movie", "tmdb_id": 99, "relation": "recommendations"}])
        self.seed("movie:1")
        client = AsyncMock()
        client._get.return_value = {"results": [{"id": 99, "title": "Related", "name": "Related", "genre_ids": [878], "original_language": "en"}]}
        client.movie_details.return_value = CatalogDetails(tmdb_id=99, media_type="movie", title="Related", genre_refs=[{"tmdb_id": 878, "name": "Sci-Fi"}])
        taste = build_taste(self.db, self.profile)
        sources, _ = asyncio.run(warm(self.db, self.profile, taste, client=client))
        candidates = LocalCandidates().generate(self.db, taste, baseline_keys=sources)
        related = next(c for c in candidates if c.entity.key == "movie:99")
        self.assertIn("movie:1", related.related_to)
        self.assertLessEqual(client._get.await_count + client.movie_details.await_count, POLICY.upstream_budget)
        self.assertEqual(len([c for c in candidates if c.entity.key == "movie:99"]), 1)

    def test_remote_failure_is_optional_and_negative_cached(self):
        from metadata.tmdb import TMDBError
        client = AsyncMock()
        client._get.side_effect = TMDBError(503, "Unavailable")
        taste = build_taste(self.db, self.profile)
        first = asyncio.run(warm(self.db, self.profile, taste, client=client))
        second = asyncio.run(warm(self.db, self.profile, taste, client=client))
        self.assertEqual(first, second)
        self.assertEqual(first[1], ["Unavailable"])
        self.assertEqual(client._get.await_count, 4)

    def test_localized_feed_items_and_new_catalog_do_not_move_existing_cursor(self):
        for n in range(1, 20):
            self.put(n)
            store_metadata(self.db, "tr-TR", CatalogDetails(tmdb_id=n, media_type="movie", title=f"Türkçe {n}", original_title=f"Title {n}", genre_refs=[{"tmdb_id": 878, "name": "Bilim Kurgu"}], original_language="en"))
        self.db.commit()
        self.profile.locale = "tr-TR"
        self.db.commit()
        first = self.page(batch_size=1)
        second = self.page(batch_size=1, cursor=first["next_cursor"])
        self.put(100, popularity=500)
        self.assertEqual(second, self.page(batch_size=1, cursor=first["next_cursor"]))
        self.assertTrue(all(i["title"].startswith("Türkçe") for s in first["shelves"] + second["shelves"] for i in s["items"]))

    def test_strong_different_profile_preferences_change_ranking(self):
        self.put(1, genre=878, keywords=[])
        self.put(2, genre=35, keywords=[])
        self.put(3, genre=878, keywords=[])
        self.put(4, genre=35, keywords=[])
        self.seed("movie:1")
        self.seed("movie:2", profile=self.other)
        _, a = self.rank()
        _, b = self.rank(self.other)
        a = [r for r in a if not r.exclusion]
        b = [r for r in b if not r.exclusion]
        self.assertEqual(a[0].candidate.entity.key, "movie:3")
        self.assertEqual(b[0].candidate.entity.key, "movie:4")

    def test_all_history_seen_suppression_beyond_recent_taste_window(self):
        self.put(1)
        self.put(2)
        self.progress("movie:1", 5400, completions=1, days_ago=200)
        self.progress("movie:2", 1200)
        result = self.page(policy=replace(POLICY, progress_limit=1))
        snapshot = self.db.get(SearchCache, result["snapshot_id"])
        candidates = snapshot.data["diagnostics"]["candidates"]
        self.assertEqual(next(c for c in candidates if c["key"] == "movie:1")["exclusion"], "seen_or_active_series")

    def test_person_keyword_company_affinity_diagnostics(self):
        credits = [{"tmdb_id": i, "name": role, "role": role} for i, role in enumerate(("Actor", "Director", "Creator", "Producer"), 1)]
        companies = [{"tmdb_id": 1, "name": "Studio"}]
        self.put(1, credits=credits, production_companies=companies)
        self.put(2, credits=credits, production_companies=companies)
        self.seed("movie:1")
        taste, ranked = self.rank()
        parts = next(r.contributions for r in ranked if r.candidate.entity.key == "movie:2")
        for name in ("genre", "keyword", "cast", "director", "creator", "producer", "company"):
            self.assertGreater(parts[name + "_affinity"], 0)

    def test_signature_changes_for_list_rewatch_progression_and_feedback(self):
        self.put(1, "tv", anime=True)
        before = signal_signature(self.db, self.profile)
        self.intent("tv:1", listed=True)
        self.assertNotEqual(before, signal_signature(self.db, self.profile))
        first = self.progress("tv:1", 1500, episode=1, days_ago=7)
        before = signal_signature(self.db, self.profile)
        first.rewatches = 1
        self.db.commit()
        self.assertNotEqual(before, signal_signature(self.db, self.profile))
        before = signal_signature(self.db, self.profile)
        self.progress("tv:1", 1500, episode=2)
        self.assertNotEqual(before, signal_signature(self.db, self.profile))
        self.assertGreater(build_taste(self.db, self.profile).signals["tv:1"]["contributions"]["progression"], 0)
        self.assertIn("anime", build_taste(self.db, self.profile).domains)
        before = signal_signature(self.db, self.profile)
        self.intent("tv:1", negative=True)
        self.assertNotEqual(before, signal_signature(self.db, self.profile))

    def test_anime_remains_searchable_and_browsable_with_no_feed_affinity(self):
        from metadata.index import candidates
        from metadata.search import surface
        self.put(1, anime=True, title="Anime Test")
        self.assertTrue(candidates(self.db, "Anime Test"))
        self.assertEqual(surface(self.db, "en-US")["results"][0]["key"], "movie:1")
        self.assertEqual(self.page()["shelves"], [])

    def test_candidate_budget_with_large_catalog_and_home_type_diversity(self):
        from metadata.catalog import entity
        from recommendations.features import reindex_features
        for n in range(1, 651):
            kind = "movie" if n % 2 else "tv"
            row = entity(self.db, kind, n, f"Catalog {n}", {"genre_refs": [{"tmdb_id": 878}], "original_language": "en", "popularity": 20})
            reindex_features(self.db, row.key)
        self.db.commit()
        self.seed("movie:1")
        taste = build_taste(self.db, self.profile)
        candidates = LocalCandidates().generate(self.db, taste)
        self.assertLessEqual(len(candidates), POLICY.candidate_limit)
        ranked = HybridRecommender().rank(taste, candidates)
        selected = diversify(ranked, 6)
        self.assertEqual({r.candidate.entity.kind for r in selected}, {"movie", "tv"})
        for kind in ("movie", "tv"):
            self.assertTrue(all(c.entity.kind == kind for c in LocalCandidates().generate(self.db, taste, kind)))

    def test_recommender_can_be_replaced_without_changing_feed_contract(self):
        self.put(1)
        class Replacement:
            version = "test-replacement"
            def rank(self, taste, candidates):
                return []
        result = self.page(engine=Replacement())
        self.assertEqual(result["shelves"], [])
        self.assertEqual(result["surface"], "home")
        self.assertIsNone(result["next_cursor"])

    def test_disliked_onboarding_seed_cannot_boost_related_titles(self):
        self.put(1, related=[{"media_type": "movie", "tmdb_id": 2, "relation": "recommendations"}])
        self.put(2)
        self.seed("movie:1")
        self.intent("movie:1", negative=True)
        taste = build_taste(self.db, self.profile)
        candidates = LocalCandidates().generate(self.db, taste, baseline_keys={"/movie/1/recommendations": ["movie:2"]})
        ranked = HybridRecommender().rank(taste, candidates)
        self.assertEqual(next(r for r in ranked if r.candidate.entity.key == "movie:2").contributions["onboarding_similarity"], 0)
