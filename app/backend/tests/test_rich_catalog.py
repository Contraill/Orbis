import asyncio
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from db.base import Base
import db.models
from db.models.catalog import CatalogEntity, CatalogLink, CatalogEpisode, SearchCache
from db.models.foundation import LocalizedMetadata
from db.models.profile import utc_now
from metadata.schemas import CatalogDetails, CatalogItem, SeasonDetails, EpisodeSummary
from metadata.localization import store_metadata
from metadata.catalog import cached, display, ratings
from metadata.index import candidates, normalize
from metadata.search import search, surface, person_credits
from metadata.ratings import import_imdb
from metadata.tmdb import TMDBError, rich_fields


class RichCatalogTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.client = AsyncMock()
        self.client._get.side_effect = AssertionError("Unexpected upstream request")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def put(self, locale="en-US", **kw):
        values = dict(tmdb_id=157336, media_type="movie", title="Interstellar", original_title="Interstellar", aliases=["Yıldızlararası"], credits=[
            {"tmdb_id": 525, "name": "Christopher Nolan", "role": "Director"},
            {"tmdb_id": 689, "name": "Emma Thomas", "role": "Producer"},
            {"tmdb_id": 10297, "name": "Matthew McConaughey", "role": "Actor", "character": "Cooper"},
        ], production_companies=[{"tmdb_id": 923, "name": "Legendary Pictures"}], external_ids={"imdb": "tt0816692"})
        values.update(kw)
        store_metadata(self.db, locale, CatalogDetails(**values))
        self.db.commit()

    def run_search(self, q, **kw):
        return asyncio.run(search(self.db, self.client, q, kw.pop("locale", "en-US"), **kw))

    def test_localizations_preserved_and_details_cache_not_renewed_by_summary(self):
        self.put(overview="English")
        self.put("tr-TR", title="Yıldızlararası", overview="Türkçe")
        self.assertEqual(cached(self.db, "movie:157336", "en-US", True)["overview"], "English")
        self.assertEqual(cached(self.db, "movie:157336", "tr-TR", True)["overview"], "Türkçe")
        row = self.db.get(LocalizedMetadata, ("movie:157336", "en-US"))
        row.fetched_at = utc_now() - timedelta(days=2)
        self.db.commit()
        store_metadata(self.db, "en-US", CatalogItem(tmdb_id=157336, media_type="movie", title="Summary"))
        self.assertIsNone(cached(self.db, "movie:157336", "en-US", True))
        self.assertEqual(row.data["overview"], "English")
        self.assertEqual(len(list(self.db.scalars(select(CatalogEntity).where(CatalogEntity.kind == "movie")))), 1)

    def test_titles_partial_typo_case_diacritics_roles_and_company(self):
        self.put()
        self.put("tr-TR", title="Yıldızlararası")
        for query in ["Interstellar", "interst", "interstelar", "YILDIZLARARASI", "Matthew McConaughey", "christoper nolan", "Emma Thomas", "Legendary"]:
            with self.subTest(query=query):
                found = self.run_search(query)
                self.assertIn("movie:157336", [r["key"] for r in found["results"]])
        for query, role in [("Matthew", "Actor"), ("christoper nolan", "Director"), ("Emma", "Producer")]:
            found = self.run_search(query, kind="person")
            self.assertIn(role, found["results"][0]["roles"])
        self.assertEqual(self.run_search("legendary", kind="company")["results"][0]["kind"], "company")
        self.assertEqual(normalize("KARA ŞÖVALYE: İSTANBUL ı"), "kara sovalye istanbul i")

    def test_alternate_language_discovery_and_display_only_changes_with_locale(self):
        self.put(tmdb_id=155, title="The Dark Knight", original_title="The Dark Knight", aliases=["Batman: The Dark Knight"])
        self.put("tr-TR", tmdb_id=155, title="Kara Şövalye", original_title="The Dark Knight", aliases=[])
        for locale in ("en-US", "tr-TR"):
            for query in ("The Dark Knight", "kara sovalye", "Batman"):
                result = self.run_search(query, locale=locale)["results"][0]
                self.assertEqual(result["key"], "movie:155")
                self.assertEqual(result["title"], "The Dark Knight" if locale == "en-US" else "Kara Şövalye")

    def test_creator_and_local_credit_discovery(self):
        self.put(media_type="tv", tmdb_id=9, title="Series", credits=[{"tmdb_id": 5, "name": "Series Creator", "role": "Creator"}])
        person = self.run_search("Series Creator", kind="person")["results"][0]
        self.assertEqual(person["roles"], ["Creator"])
        found = surface(self.db, "en-US", entity_key=person["key"])
        self.assertEqual(found["results"][0]["key"], "tv:9")

    def test_remote_cache_dedup_and_pagination_beyond_first_page(self):
        self.put()
        async def upstream(path, params):
            if path == "/search/company":
                return {"results": [], "total_pages": 0}
            return {"total_pages": 3, "results": [{"media_type": "movie", "id": 157336 if params["page"] == 1 else params["page"], "title": "Interstellar"}]}
        self.client._get.side_effect = upstream
        first = self.run_search("interstellar", limit=1, online=True)
        self.assertEqual(self.client._get.call_count, 0)
        second = self.run_search("interstellar", limit=1, online=True, cursor=first["next_cursor"])
        self.assertEqual(second["results"], [])  # duplicate-only remote page still advances
        third = self.run_search("interstellar", limit=1, online=True, cursor=second["next_cursor"])
        self.assertEqual(third["results"][0]["key"], "movie:2")
        calls = self.client._get.call_count
        self.assertEqual(third, self.run_search("interstellar", limit=1, online=True, cursor=second["next_cursor"]))
        self.assertEqual(self.client._get.call_count, calls)
        fourth = self.run_search("interstellar", limit=1, online=True, cursor=third["next_cursor"])
        self.assertEqual(fourth["results"][0]["key"], "movie:3")
        self.assertIsNone(fourth["next_cursor"])

    def test_fallback_negative_cache_and_failure_retry(self):
        self.client._get.side_effect = None
        self.client._get.return_value = {"results": [], "total_pages": 0}
        self.run_search("nothing")
        self.run_search("nothing")
        self.assertEqual(self.client._get.call_count, 2)
        self.client._get.side_effect = TMDBError(503, "Unavailable")
        failed = self.run_search("missing")
        self.assertEqual(failed["warning"], "Unavailable")
        self.assertIsNotNone(failed["next_cursor"])

    def test_cursor_scope_expiry_and_snapshot_order(self):
        for n in range(5):
            self.put(tmdb_id=n + 1, title=f"Interstellar {n}")
        first = self.run_search("interstellar", limit=2)
        self.put(tmdb_id=1000, title="Interstellar New")
        second = self.run_search("interstellar", limit=2, cursor=first["next_cursor"])
        self.assertFalse({r["key"] for r in first["results"]} & {r["key"] for r in second["results"]})
        self.assertNotIn("movie:1000", [r["key"] for r in second["results"]])
        with self.assertRaises(HTTPException) as caught:
            self.run_search("different", limit=2, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 422)
        row = self.db.get(SearchCache, first["next_cursor"])
        row.expires_at = utc_now() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.run_search("interstellar", limit=2, cursor=first["next_cursor"])
        self.assertEqual(caught.exception.status_code, 410)

    def test_realistic_bounded_candidates_and_fts_query_plan(self):
        from metadata.catalog import entity
        from metadata.index import reindex
        for i in range(1200):
            row = entity(self.db, "movie", i, f"Unrelated adventure number {i}")
            reindex(self.db, row.key)
        self.put()
        hits = candidates(self.db, "interstelar")
        self.assertEqual(hits[0][0], "movie:157336")
        self.assertLessEqual(len(candidates(self.db, "adventure")), 600)
        plan = self.db.execute(text("EXPLAIN QUERY PLAN SELECT key FROM catalog_fts WHERE catalog_fts MATCH 'terms:interst*' LIMIT 300")).all()
        self.assertIn("VIRTUAL TABLE INDEX", str(plan))

    def test_person_enrichment_and_repeated_cache(self):
        self.client._get.side_effect = None
        self.client._get.return_value = {"id": 525, "name": "Christopher Nolan", "combined_credits": {"crew": [{"media_type": "movie", "id": 99, "title": "Film", "job": "Director"}]}}
        asyncio.run(person_credits(self.db, self.client, 525, "en-US"))
        asyncio.run(person_credits(self.db, self.client, 525, "en-US"))
        self.assertEqual(self.client._get.call_count, 1)
        self.assertEqual(surface(self.db, "en-US", entity_key="person:525")["results"][0]["key"], "movie:99")

    def test_season_episode_localization(self):
        for locale, name in [("en-US", "Pilot"), ("tr-TR", "Başlangıç")]:
            store_metadata(self.db, locale, SeasonDetails(series_tmdb_id=5, season_tmdb_id=20, season_number=1, name=name, episodes=[EpisodeSummary(tmdb_id=30, episode_number=1, name=name)]))
        self.db.commit()
        self.assertEqual(len(list(self.db.scalars(select(CatalogEpisode)))), 1)
        self.assertEqual(cached(self.db, "tv:5:season:1", "en-US")["episodes"][0]["name"], "Pilot")
        self.assertEqual(cached(self.db, "tv:5:season:1", "tr-TR")["episodes"][0]["name"], "Başlangıç")

    def test_rich_fields_and_optional_streamed_ratings(self):
        fields = rich_fields({"genres": [{"id": 1, "name": "Drama"}], "keywords": {"results": [{"id": 2, "name": "space"}]}, "created_by": [{"id": 3, "name": "Creator"}], "external_ids": {"imdb_id": "tt0816692", "facebook_id": None}, "videos": {"results": [{"site": "YouTube", "key": "abc", "type": "Trailer", "official": True, "iso_639_1": "tr"}]}})
        self.assertEqual(fields["external_ids"], {"imdb": "tt0816692"})
        self.assertEqual(fields["credits"][0]["role"], "Creator")
        self.assertEqual(fields["videos"][0]["language"], "tr")
        self.put()
        self.assertEqual(ratings(self.db, "movie:157336"), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ratings.tsv.gz"
            with gzip.open(path, "wt") as stream:
                stream.write("tconst\taverageRating\tnumVotes\ntt0816692\t8.7\t1234\ntt0000000\t1.0\t2\n")
            self.assertEqual(import_imdb(self.db, path), 1)
        self.assertEqual(ratings(self.db, "movie:157336")[0]["votes"], 1234)

    def test_surface_keyset_filters_and_concurrent_inserts(self):
        self.put(tmdb_id=1)
        self.put(tmdb_id=3)
        self.put(media_type="tv", tmdb_id=2)
        first = surface(self.db, "en-US", limit=1)
        self.put(tmdb_id=2)  # sorts into the middle, but was added after traversal began
        second = surface(self.db, "en-US", limit=1, cursor=first["next_cursor"])
        self.assertEqual(second["results"][0]["key"], "movie:3")
        third = surface(self.db, "en-US", limit=1, cursor=second["next_cursor"])
        self.assertEqual(third["results"][0]["key"], "tv:2")
        self.assertIsNone(third["next_cursor"])
        movies = surface(self.db, "en-US", kind="movie")
        self.assertEqual(len(movies["results"]), 3)
        series = surface(self.db, "en-US", kind="tv")
        self.assertEqual(len(series["results"]), 1)
        from db.models.profile import Profile
        from db.models.foundation import LibraryIntent
        profile = Profile(name="Viewer")
        self.db.add(profile)
        self.db.flush()
        self.db.add(LibraryIntent(profile_id=profile.id, media_type="tv", tmdb_id=2, in_my_list=True))
        self.db.commit()
        saved = surface(self.db, "en-US", my_list=True, profile_id=profile.id)
        self.assertEqual([r["key"] for r in saved["results"]], ["tv:2"])

    def test_prefix_and_fuzzy_work_on_non_title_names(self):
        self.put()
        self.assertEqual(candidates(self.db, "chris", "person")[0][0], "person:525")
        self.assertEqual(candidates(self.db, "legandary pictures", "company")[0][0], "company:923")
        self.assertEqual(candidates(self.db, "!!!"), [])
        self.run_search("in")
        self.client._get.assert_not_called()

    def test_same_locale_refresh_updates_index_without_losing_other_locale(self):
        self.put()
        self.put("tr-TR", title="Yıldızlararası")
        self.put(title="New Localized Title", original_title="Interstellar")
        self.assertEqual(candidates(self.db, "New Localized")[0][0], "movie:157336")
        self.assertEqual(display(self.db, "movie:157336", "tr-TR")["title"], "Yıldızlararası")

    def test_locale_title_tie_break_changes_ranking_not_discoverability(self):
        self.put(tmdb_id=1, title="Hero", original_title="First film", aliases=["Hero"])
        self.put("tr-TR", tmdb_id=1, title="İlk film", original_title="First film", aliases=["Hero"])
        self.put(tmdb_id=2, title="Second film", original_title="Second film", aliases=["Hero"])
        self.put("tr-TR", tmdb_id=2, title="Hero", original_title="Second film", aliases=["Hero"])
        english = self.run_search("Hero", locale="en-US")["results"]
        turkish = self.run_search("Hero", locale="tr-TR")["results"]
        self.assertEqual([r["key"] for r in english], ["movie:1", "movie:2"])
        self.assertEqual([r["key"] for r in turkish], ["movie:2", "movie:1"])
