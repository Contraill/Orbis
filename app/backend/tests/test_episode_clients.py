import unittest
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select, func
from test_playback_hardening import HardeningTestCase, SequencedProvider, source
from db.models.profile import utc_now, Profile
from db.models.foundation import ViewingProgress
from db.models.playback import PlaybackState
from db.models.client_session import ClientSession, ContentMarkers
from metadata.localization import store_metadata
from metadata.schemas import CatalogDetails, SeasonDetails, EpisodeSummary
from playback.capabilities import ClientCapabilities, source_compatible, filter_hls, ClientCompatibilityError
from playback.choices import manifest_qualities
from playback.source_sessions import source_sessions, SourceSessionNotFound
from playback.schemas import EpisodeMarkers
from client_sessions.service import cleanup
from db.models.catalog import CatalogEpisode
from db.models.foundation import LocalizedMetadata, Installation
from core.auth import issue_session
from playback.capabilities import request_client
from playback.delivery import delivery_broker
from playback.hls import rewrite_manifest

MASTER = '#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=3840x2160,CODECS="hvc1.1,mp4a.40.2",VIDEO-RANGE=PQ\n4k.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"\n1080.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"\n720.m3u8\n'


class CapabilityTests(unittest.TestCase):
    def test_broker_enforces_compatible_master_without_relaying_segments(self):
        token = request_client.set({'id': 'client', 'capabilities': {'max_height':720}})
        try:
            entry = delivery_broker.issue(1, 'movie:1', source('test', 'master'), 'audience')
            self.assertTrue({'root', 'manifest'}.issubset(entry.plan.relay))
            rewritten = rewrite_manifest(entry, entry.resources['root'], entry.source.url, MASTER)
            self.assertNotIn('3840x2160', rewritten)
            self.assertNotIn('1920x1080', rewritten)
            self.assertIn('1280x720', rewritten)
            self.assertFalse(any('4k.m3u8' in r.url for r in entry.resources.values()))
        finally:
            request_client.reset(token)
            source_sessions.clear()

    def test_capabilities_variants_and_missing_fallback(self):
        caps = ClientCapabilities(max_height=1080, video_codecs=["h264"], audio_codecs=["aac"], hdr=False)
        filtered = filter_hls(MASTER, caps)
        self.assertNotIn('4k.m3u8', filtered)
        self.assertEqual([q.height for q in manifest_qualities(filtered)], [1080, 720])
        self.assertEqual(filter_hls(MASTER, None), MASTER)
        self.assertFalse(source_compatible(source('x', '4k', protocol='http', quality='2160p'), caps))
        self.assertTrue(source_compatible(source('x', 'master', quality='2160p'), caps))
        self.assertFalse(source_compatible(source('x', 'dash', protocol='dash'), ClientCapabilities(dash=False)))
        with self.assertRaises(ClientCompatibilityError):
            filter_hls(MASTER, ClientCapabilities(video_codecs=["av1"]))

    def test_markers_optional_and_ordered(self):
        self.assertTrue(all(v is None for v in EpisodeMarkers().model_dump().values()))
        self.assertEqual(EpisodeMarkers(intro_start=10, intro_end=40, credits_start=1800).credits_end, None)
        with self.assertRaises(ValueError):
            EpisodeMarkers(recap_start=100, recap_end=20)
        with self.assertRaises(ValueError):
            EpisodeMarkers(credits_start=float('inf'))


class EpisodeClientTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        sources = [source('multi', '4k', protocol='http', quality='2160p'), source('multi', '720', protocol='http', quality='720p')]
        for s in sources:
            s.source_id = 'host'
            s.video_codec = 'h264'
        self.provider = SequencedProvider('multi', 10, [sources])
        for mock in self.provider_patches([self.provider]):
            mock.start()
            self.addCleanup(mock.stop)
        self.root = f'/api/playback/profiles/{self.profile.id}/tv/42/season/1/episode/1'
        store_metadata(self.db, 'en-US', CatalogDetails(tmdb_id=42, media_type='tv', title='Series', status='Ended', seasons=[
            {'tmdb_id':1, 'season_number':1, 'name':'First', 'episode_count':2},
            {'tmdb_id':2, 'season_number':2, 'name':'Last', 'episode_count':1}]))
        for season, count in [(1,2), (2,1)]:
            store_metadata(self.db, 'en-US', SeasonDetails(series_tmdb_id=42, season_tmdb_id=season, season_number=season, name=f'Season {season}', episodes=[
                EpisodeSummary(tmdb_id=season*100+n, episode_number=n, name=f'Episode {n}', air_date='2020-01-01') for n in range(1,count+1)]))
        self.db.commit()

    def register(self, profile_id=None, caps=None):
        response = self.client.post('/api/sessions', json={'profile_id':profile_id or self.profile.id, 'display_name':'Test browser', 'capabilities':caps})
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.client.headers['X-Orbis-Session'] = session['id']
        return session['id']

    def test_episode_neighbors_season_boundary_and_final(self):
        first = self.client.get(self.root + '/lifecycle').json()
        self.assertIsNone(first['previous'])
        self.assertEqual(first['next']['episode_number'], 2)
        self.assertTrue(first['autoplay_allowed'])
        self.assertFalse(first['is_final_episode'])
        boundary = self.client.get(self.root.replace('episode/1','episode/2') + '/lifecycle').json()
        self.assertTrue(boundary['season_transition'])
        self.assertEqual(boundary['next']['season_number'], 2)
        final = self.client.get(self.root.replace('season/1','season/2') + '/lifecycle').json()
        self.assertEqual(final['previous']['episode_number'], 2)
        self.assertTrue(final['is_final_episode'])
        self.assertEqual(final['next_status'], 'series_finished')
        self.assertIsNone(final['next'])
        self.profile.autoplay_next_episode = False
        self.db.commit()
        self.assertFalse(self.client.get(self.root + '/lifecycle').json()['autoplay_allowed'])

    def test_prepare_does_not_write_state_history_or_current_session_and_promotes(self):
        session_id = self.register(caps={'max_height':1080})
        current = self.client.post(self.root + '/resolve').json()
        self.assertEqual(current['selected_source']['quality'], '720p')
        self.assertEqual(self.client.put(self.root+'/state', json={'position_seconds':120, 'duration_seconds':2400, 'preferred_quality_height':1080}).status_code, 200)
        self.db.expire_all()
        states_before = self.db.scalar(select(func.count()).select_from(PlaybackState))
        history_before = self.db.scalar(select(func.count()).select_from(ViewingProgress))
        prepared = self.client.post(self.root+'/prepare-next')
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertTrue(prepared.json()['preparation_only'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PlaybackState)), states_before)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)), history_before)
        presence = self.client.get('/api/sessions/'+session_id).json()
        self.assertEqual(presence['current_playback']['episode_number'], 1)
        self.assertEqual(self.client.patch('/api/sessions/'+session_id, json={'state':'playing','source_session_id':prepared.json()['source_session_id']}).status_code, 409)
        calls = self.provider.calls
        moved = self.client.post(self.root+'/transition', json={'direction':'next','prepared_source_session_id':prepared.json()['source_session_id']})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()['state']['episode_number'], 2)
        self.assertEqual(moved.json()['state']['preferred_quality_height'], 1080)
        self.assertFalse(moved.json()['preparation_only'])
        self.assertEqual(self.provider.calls, calls)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)), history_before)
        self.assertEqual(self.client.get('/api/sessions/'+session_id).json()['current_playback']['episode_number'], 2)

    def test_session_update_stop_cleanup_revoke_and_isolation(self):
        session_id = self.register()
        resolved = self.client.post(self.root+'/resolve').json()
        updated = self.client.patch('/api/sessions/'+session_id, json={'state':'playing','source_session_id':resolved['source_session_id'], 'position_seconds':99})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['position_seconds'], 99)
        self.assertIsNotNone(updated.json()['started_at'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)), 0)
        other = Profile(name='Other')
        self.db.add(other)
        self.db.commit()
        wrong = self.root.replace(f'profiles/{self.profile.id}', f'profiles/{other.id}')
        self.assertEqual(self.client.post(wrong+'/resolve').status_code, 404)
        stopped = self.client.patch('/api/sessions/'+session_id, json={'state':'stopped','source_session_id':resolved['source_session_id']})
        self.assertEqual(stopped.json()['state'], 'stopped')
        self.assertIsNone(stopped.json()['current_playback'])
        with self.assertRaises(SourceSessionNotFound):
            source_sessions.get(resolved['source_session_id'])
        self.client.post(self.root+'/resolve')
        self.db.expire_all()
        row = self.db.get(ClientSession, session_id)
        row.last_seen = utc_now() - timedelta(minutes=3)
        self.db.commit()
        cleanup(self.db)
        self.db.commit()
        self.assertEqual(row.state, 'stale')
        self.assertIsNone(row.current_playback)
        self.assertEqual(self.client.delete('/api/sessions/'+session_id).status_code, 200)
        self.assertEqual(self.client.post(self.root+'/resolve').status_code, 403)
        row.last_seen = utc_now() - timedelta(days=2)
        self.db.commit()
        cleanup(self.db)
        self.db.commit()
        self.assertIsNone(self.db.get(ClientSession, session_id))

    def test_explicit_incompatible_quality_fallback_and_default_legacy(self):
        legacy = self.client.post(self.root+'/resolve').json()
        self.assertEqual(legacy['selected_source']['quality'], '2160p')
        self.register(caps={'max_height':720})
        resolved = self.client.post(self.root+'/resolve').json()
        self.assertEqual(resolved['selected_source']['quality'], '720p')
        chosen = self.client.post(self.root+'/choices', json={'source_session_id':resolved['source_session_id'], 'preferred_quality_height':1080})
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(chosen.json()['choices']['quality_outcome'], 'incompatible_fallback')
        self.assertEqual(chosen.json()['choices']['selected_quality_height'], 720)
        self.assertEqual(chosen.json()['state']['preferred_quality_height'], 1080)

    def test_optional_stored_markers_and_resume(self):
        self.db.add(ContentMarkers(content_key='tv:42:s1:e1', markers={'intro_start':0,'intro_end':70,'credits_start':1800}, source='manual'))
        self.db.commit()
        self.client.put(self.root+'/state', json={'position_seconds':110,'duration_seconds':2000})
        result = self.client.get(self.root+'/lifecycle').json()
        self.assertEqual(result['resume_position_seconds'], 110)
        self.assertEqual(result['markers']['intro_end'],70)
        self.assertIsNone(result['markers']['recap_start'])
        self.assertEqual(result['marker_source'], 'manual')

    def test_unknown_missing_and_future_episode_are_not_series_finished(self):
        following = self.db.get(CatalogEpisode, ('tv:42', 1, 2))
        following.air_date = '2999-01-01'
        self.db.commit()
        result = self.client.get(self.root+'/lifecycle').json()
        self.assertEqual(result['next_status'], 'unreleased')
        self.assertFalse(result['autoplay_allowed'])
        self.assertEqual(self.client.post(self.root+'/transition', json={}).status_code, 409)
        self.db.delete(following)
        self.db.commit()
        self.assertEqual(self.client.get(self.root+'/lifecycle').json()['next_status'], 'metadata_incomplete')
        metadata = self.db.get(LocalizedMetadata, ('tv:42','en-US'))
        metadata.data = {**metadata.data, 'status':'Returning Series'}
        self.db.commit()
        result = self.client.get(self.root.replace('season/1','season/2')+'/lifecycle').json()
        self.assertFalse(result['is_final_episode'])
        self.assertEqual(result['next_status'], 'metadata_incomplete')

    def test_completion_preserves_preparation_and_previous_can_resume(self):
        session_id = self.register()
        first = self.client.post(self.root+'/resolve').json()
        prepared = self.client.post(self.root+'/prepare-next').json()
        saved = self.client.put(self.root+'/state', json={'position_seconds':2400,'duration_seconds':2400,'completed':True})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get('/api/sessions/'+session_id).json()['state'], 'stopped')
        count = self.db.scalar(select(func.count()).select_from(ViewingProgress))
        calls = self.provider.calls
        next_response = self.client.post(self.root+'/transition', json={'prepared_source_session_id':prepared['source_session_id']})
        self.assertEqual(next_response.status_code, 200, next_response.text)
        self.assertEqual(self.provider.calls, calls)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)), count)
        stale_stop = self.client.patch('/api/sessions/'+session_id, json={'state':'stopped','source_session_id':first['source_session_id']})
        self.assertEqual(stale_stop.status_code,409)
        self.assertEqual(self.client.get('/api/sessions/'+session_id).json()['current_playback']['episode_number'],2)
        previous = self.client.post(self.root.replace('episode/1','episode/2')+'/transition',json={'direction':'previous'})
        self.assertEqual(previous.status_code,200,previous.text)
        self.assertEqual(previous.json()['state']['episode_number'],1)

    def test_missing_preparation_falls_back_and_preserves_destination_resume(self):
        target = self.root.replace('episode/1','episode/2')
        self.client.put(target+'/state', json={'position_seconds':450,'duration_seconds':2400})
        self.register()
        self.client.post(self.root+'/resolve')
        result = self.client.post(self.root+'/transition',json={'prepared_source_session_id':'expired'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state']['position_seconds'],450)

    def test_same_profile_clients_and_admin_authority(self):
        first_id = self.register()
        first = self.client.post(self.root+'/resolve').json()
        second_id = self.register()
        second = self.client.post(self.root+'/resolve').json()
        rejected = self.client.patch('/api/sessions/'+second_id,json={'state':'playing','source_session_id':first['source_session_id']})
        self.assertEqual(rejected.status_code,409)
        self.assertEqual(self.client.get('/api/admin/sessions').status_code,401)
        marker_url = '/api/admin/episode-markers/tv/42/season/1/episode/1'
        self.assertEqual(self.client.put(marker_url,json={'source':'manual','intro_end':50}).status_code,401)
        cookie = self.client.cookies.get('playback_client')
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/sessions/'+first_id).status_code,404)
        self.client.cookies.set('playback_client',cookie)
        self.profile.is_owner = True
        self.db.add(Installation(id=1,owner_id=self.profile.id,locale='en-US'))
        token = issue_session(self.db,self.profile.id)
        self.db.commit()
        self.client.headers['Authorization'] = 'Bearer '+token
        response = self.client.get('/api/admin/sessions')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()),2)
        self.assertNotIn('audience',response.json()[0])
        self.assertEqual(self.client.put(marker_url,json={'source':'manual','intro_end':50}).status_code,200)
        self.assertEqual(self.client.delete('/api/admin/sessions/'+first_id).status_code,200)
        with self.assertRaises(SourceSessionNotFound):
            source_sessions.get(first['source_session_id'])
        self.assertIsNotNone(source_sessions.get(second['source_session_id']))

    def test_no_compatible_source_has_normalized_outcome(self):
        self.register(caps={'video_codecs':['av1']})
        response = self.client.post(self.root+'/resolve')
        self.assertEqual(response.status_code,409,response.text)
        self.assertIn('no_compatible_source', response.text)

    def test_compatible_provider_fallback_and_context_does_not_leak(self):
        bad = source('first','unsupported',protocol='http',quality='2160p')
        good = source('second','supported',protocol='http',quality='720p')
        first = SequencedProvider('first',1,[[bad]])
        second = SequencedProvider('second',2,[[good]])
        patches = self.provider_patches([first,second])
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.register(caps={'max_height':720})
        response = self.client.post(self.root+'/resolve')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['selected_source']['provider_id'],'second')
        del self.client.headers['X-Orbis-Session']
        # A different request without capabilities retains legacy behavior.
        fresh = self.client.post(self.root.replace('/tv/42/','/tv/43/')+'/resolve')
        self.assertEqual(fresh.status_code,200,fresh.text)
        self.assertEqual(fresh.json()['selected_source']['provider_id'],'first')

    def test_bounded_recent_session_storage(self):
        with patch('client_sessions.service.MAX_SESSIONS',3):
            ids = [self.register() for _ in range(4)]
            self.assertEqual(self.db.scalar(select(func.count()).select_from(ClientSession)),3)
            cleanup(self.db)
            self.db.commit()
            self.assertEqual(self.db.scalar(select(func.count()).select_from(ClientSession)),3)
            self.assertIsNone(self.db.get(ClientSession,ids[0]))

    def test_revoke_during_resolution_does_not_resurrect_presence(self):
        session_id = self.register()
        async def revoke_while_resolving(*args):
            with self.sessions() as concurrent:
                row = concurrent.get(ClientSession,session_id)
                row.revoked_at, row.state = utc_now(), 'revoked'
                concurrent.commit()
            return self.provider.next_sources()
        with patch.object(self.provider,'resolve_episode',side_effect=revoke_while_resolving):
            result = self.client.post(self.root+'/resolve')
        self.assertEqual(result.status_code,200,result.text)
        with self.assertRaises(SourceSessionNotFound):
            source_sessions.get(result.json()['source_session_id'])
        self.db.expire_all()
        row = self.db.get(ClientSession,session_id)
        self.assertEqual(row.state,'revoked')
        self.assertIsNone(row.current_playback)
