import asyncio
import unittest
from unittest.mock import patch

from playback.choices import manifest_qualities, selected_height
from playback.delivery import DeliveryUnavailable
from playback.delivery_policy import DeliveryPlan
from playback.schemas import PlaybackPreferences, PlaybackStateUpdate
from playback.service import movie_identity, upsert_playback_state
from playback.source_sessions import source_sessions
from test_playback_hardening import HardeningTestCase, SequencedProvider, source


MASTER = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1920x1080\na.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=900000\nb.m3u8\n'


class QualityTests(unittest.TestCase):
    def test_actual_variants_only_normalized_unique_descending(self):
        qualities = manifest_qualities(MASTER + '#EXT-X-STREAM-INF:RESOLUTION=1280x720\nc.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=640x360\n')
        self.assertEqual([q.height for q in qualities], [1080, 720])
        self.assertIsNone(selected_height(qualities, None))
        self.assertEqual(selected_height(qualities, 900), 720)
        self.assertEqual(selected_height(qualities, 360), 720)
        self.assertIsNone(selected_height([], 1080))


class ChoiceTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        self.root = f'/api/playback/profiles/{self.profile.id}/movie/42'
        self.sources = [source('multi', 'one'), source('multi', 'two')]
        for index, item in enumerate(self.sources):
            item.source_id = ['host-one', 'host-two'][index]
            item.source_label = ['Host One', 'Host Two'][index]
        self.provider = SequencedProvider('multi', 10, [self.sources])
        for mock in self.provider_patches([self.provider]):
            mock.start()
            self.addCleanup(mock.stop)
        discovery = patch('playback.choices.discover_qualities', return_value=manifest_qualities(MASTER))
        discovery.start()
        self.addCleanup(discovery.stop)

    def resolve(self):
        response = self.client.post(self.root + '/resolve')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def snapshot(self, session, **kwargs):
        result = {name: session['state'][name] for name in PlaybackStateUpdate.model_fields}
        result.update(source_session_id=session['source_session_id'], position_seconds=129,
                      duration_seconds=3600, preferred_audio_language='tr', preferred_audio_kind='dub',
                      subtitles_enabled=True, preferred_subtitle_language='tr')
        result.update(kwargs)
        return result

    def test_manual_source_and_quality_preserve_state_and_delivery(self):
        initial = self.resolve()
        self.assertEqual(len(initial['choices']['sources']), 2)
        response = self.client.post(self.root + '/choices', json=self.snapshot(initial,
            preferred_source_provider_id='multi', preferred_source_id='host-two', preferred_quality_height=720))
        self.assertEqual(response.status_code, 200, response.text)
        chosen = response.json()
        self.assertEqual(chosen['selected_source']['source_id'], 'host-two')
        self.assertEqual(chosen['choices']['selected_quality_height'], 720)
        self.assertEqual(chosen['state']['position_seconds'], 129)
        self.assertEqual(self.provider.calls, 1)
        old = source_sessions.get(chosen['source_session_id'])
        relayed = source_sessions.issue(old.profile_id, old.content_key, old.source, plan=DeliveryPlan(frozenset({'root', 'manifest', 'segment'})))
        relayed.context.update(old.context)
        chosen['source_session_id'] = relayed.session_id
        response = self.client.post(self.root + '/choices', json=self.snapshot(chosen, preferred_quality_height=1080))
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()
        self.assertEqual(changed['source_session_id'], relayed.session_id)
        self.assertTrue(changed['selected_source']['url'].startswith('/api/playback/sources/'))
        self.assertEqual(changed['choices']['selected_quality_height'], 1080)
        refreshed = self.client.post(self.root + '/refresh', json=self.snapshot(changed)).json()
        self.assertEqual(refreshed['selected_source']['source_id'], 'host-two')
        self.assertEqual(refreshed['state']['preferred_quality_height'], 1080)

    def test_playback_failure_tries_other_host_before_other_provider(self):
        initial = self.resolve()
        with patch('api.playback.delivery_broker.recover', side_effect=DeliveryUnavailable('failed')):
            response = self.client.post(self.root + '/recover', json=self.snapshot(initial, failure={'category':'media'}))
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertNotEqual(result['selected_source']['source_id'], initial['selected_source']['source_id'])
        self.assertEqual(result['selected_source']['provider_id'], 'multi')
        self.assertEqual(result['state']['preferred_audio_language'], 'tr')
        self.assertEqual(result['state']['position_seconds'], 129)
        self.assertEqual(self.provider.calls, 1)
        with patch('api.playback.delivery_broker.recover', side_effect=DeliveryUnavailable('failed')):
            self.assertEqual(self.client.post(self.root + '/recover', json=self.snapshot(result, failure={'category':'media'})).status_code, 502)

    def test_preferences_are_scoped_and_old_progress_clients_preserve_them(self):
        initial = self.resolve()
        state = self.client.post(self.root + '/choices', json=self.snapshot(initial,
            preferred_provider_id='multi', preferred_source_provider_id='multi', preferred_source_id='host-two', preferred_quality_height=720)).json()['state']
        response = self.client.put(self.root + '/state', json={'position_seconds':140})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['preferred_quality_height'], 720)
        self.assertEqual(response.json()['preferred_source_id'], 'host-two')
        self.assertIsNone(self.client.get(self.root.replace('42','43') + '/state').json())
        bad = self.snapshot(initial, preferred_source_id='host-two', preferred_source_provider_id=None)
        self.assertEqual(self.client.post(self.root + '/choices', json=bad).status_code, 422)
        bad = self.snapshot(initial, url='http://127.0.0.1/secret')
        self.assertEqual(self.client.post(self.root + '/choices', json=bad).status_code, 422)

    def test_unavailable_stable_preference_falls_back_without_erasing_it(self):
        upsert_playback_state(self.db, self.profile.id, movie_identity(42), PlaybackStateUpdate(
            preferred_provider_id='missing', preferred_source_provider_id='multi', preferred_source_id='gone', preferred_quality_height=2160))
        result = self.resolve()
        self.assertEqual(result['selected_source']['provider_id'], 'multi')
        self.assertEqual(result['choices']['selected_quality_height'], 1080)
        self.assertEqual(result['state']['preferred_provider_id'], 'missing')
        self.assertEqual(result['state']['preferred_source_id'], 'gone')

    def test_provider_override_beats_last_provider_and_profile_scope_is_enforced(self):
        other = SequencedProvider('other', 99, [[source('other','master')]])
        all_patch, get_patch = self.provider_patches([self.provider, other])
        with all_patch, get_patch:
            initial = self.resolve()
            response = self.client.post(self.root + '/choices', json=self.snapshot(initial, preferred_provider_id='other'))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['selected_source']['provider_id'], 'other')
            from db.models.profile import Profile
            profile = Profile(name='Another')
            self.db.add(profile)
            self.db.commit()
            self.assertEqual(self.client.post(f'/api/playback/profiles/{profile.id}/movie/42/choices', json=self.snapshot(initial)).status_code, 404)
            self.assertIsNone(self.client.get(f'/api/playback/profiles/{profile.id}/movie/42/state').json())
