"""V1 boundary regressions; external services are deliberately absent."""
import json
import logging
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import func, select
from test_playback_hardening import HardeningTestCase, source
from core.auth import issue_session
from core.errors import error_response
from core.maintenance import maintain, trim_cache
from db.models.catalog import SearchCache
from db.models.foundation import Installation, ViewingProgress
from db.models.profile import utc_now
from db.models.provider import ProviderEvent
from main import app
from playback.schemas import PlaybackStateUpdate
from playback.service import movie_identity, upsert_playback_state
from providers.manager import ProviderManager
from watch_together.domain import Rooms, Content, Event, RoomError
import providers.live as live


class V1HardeningTests(HardeningTestCase):
    def test_profile_deletion_cascades_history_and_revokes_transient_presence(self):
        from db.models.profile import Profile
        from playback.source_sessions import source_sessions, SourceSessionNotFound
        from watch_together.domain import rooms
        self.profile.is_owner=True
        self.db.add(Installation(id=1,owner_id=self.profile.id))
        viewer=Profile(name='Delete viewer')
        self.db.add(viewer)
        token=issue_session(self.db,self.profile.id)
        self.db.commit()
        upsert_playback_state(self.db,viewer.id,movie_identity(42),PlaybackStateUpdate(position_seconds=120),record_activity=True)
        delivery=source_sessions.issue(viewer.id,'movie:42',source('test','delete',protocol='http'))
        with rooms.lock:
            room,participant=rooms.create(SimpleNamespace(id='delete-viewer',profile_id=viewer.id),'Viewer',Content(media_type='movie',tmdb_id=42))
        try:
            response=self.client.delete(f'/api/profiles/{viewer.id}',headers={'Authorization':f'Bearer {token}'})
            self.assertEqual(response.status_code,204,response.text)
            self.assertEqual(room.status,'closed')
            self.assertNotIn(participant.id,room.participants)
            with self.assertRaises(SourceSessionNotFound): source_sessions.get(delivery.session_id)
            self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),0)
        finally:
            with rooms.lock: rooms.rooms.pop(room.id,None)

    def test_admin_authority_is_not_selected_profile(self):
        for url in ['/api/admin/playback/delivery','/api/admin/system','/api/admin/watch-together/rooms',
                    '/api/admin/sessions','/api/admin/providers']:
            result = self.client.get(url, headers={'X-Profile-ID':str(self.profile.id)})
            self.assertEqual(result.status_code,401,url)
            self.assertEqual(result.json()['error']['code'],'owner_authentication_required')
            self.assertEqual(result.headers['cache-control'],'no-store')
        self.profile.is_owner = True
        self.db.add(Installation(id=1,owner_id=self.profile.id))
        token=issue_session(self.db,self.profile.id)
        self.db.commit()
        response=self.client.get('/api/admin/system',headers={'Authorization':f'Bearer {token}'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['single_worker'])

    def test_validation_does_not_echo_credentials_and_legacy_detail_survives(self):
        response=self.client.post('/api/profiles',json={'name':'A','password':'super-secret-value'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('super-secret-value',response.text)
        self.assertIsInstance(response.json()['detail'],list)
        self.assertEqual(response.json()['error']['code'],'validation_error')
        body=json.loads(error_response(502,'Failed https://user:secret@example.com/media?token=hidden cookie=private').body)
        self.assertNotIn('hidden',json.dumps(body))
        self.assertNotIn('private',json.dumps(body))
        self.assertEqual(body['error']['code'],'upstream_error')

    def test_cache_and_event_bounds_preserve_history(self):
        upsert_playback_state(self.db,self.profile.id,movie_identity(42),PlaybackStateUpdate(position_seconds=120,duration_seconds=600),record_activity=True)
        now=utc_now()
        for index in range(8):
            self.db.add(SearchCache(key=str(index),data={},expires_at=now+timedelta(minutes=index+1)))
        self.db.flush()
        with patch('core.maintenance.MAX_CACHE_ROWS',3):
            trim_cache(self.db,'7')
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SearchCache)),3)
        with patch('core.maintenance.MAX_EVENTS',3):
            for index in range(8):
                ProviderManager()._event(self.db,'test','info','resolved',str(index))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ProviderEvent)),3)
        self.db.add(SearchCache(key='expired',data={},expires_at=now-timedelta(seconds=1)))
        self.db.commit()
        maintain(self.db)
        self.assertIsNone(self.db.get(SearchCache,'expired'))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),1)

    def test_provider_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            directory=Path(root)/'test-provider'
            directory.mkdir()
            (directory/'draft.py').symlink_to(Path(outside)/'secret')
            with patch.object(live,'LIVE_PROVIDER_ROOT',Path(root)):
                with self.assertRaises(live.LiveProviderError): live.provider_dir('test-provider')

    def test_legacy_provider_diagnostics_are_sanitized_on_read(self):
        from core.auth import require_owner
        from db.models.provider import ProviderState
        from test_playback_hardening import SequencedProvider
        provider=SequencedProvider('legacy',1,[[]])
        secret='https://upstream.example/media?token=old-secret cookie=old-cookie'
        row=ProviderState(provider_id='legacy',last_error=secret)
        self.db.add_all([row,ProviderEvent(provider_id='legacy',level='error',event='failed',message=secret)])
        self.db.commit()
        with patch('providers.manager.get_provider',return_value=provider):
            self.assertNotIn('old-secret',ProviderManager()._view(row).last_error)
        app.dependency_overrides[require_owner]=lambda:self.profile
        try:
            with patch('api.admin_providers.get_provider',return_value=provider):
                response=self.client.get('/api/admin/providers/legacy/logs')
            self.assertEqual(response.status_code,200)
            self.assertNotIn('old-secret',response.text)
            self.assertNotIn('old-cookie',response.text)
        finally:
            app.dependency_overrides.pop(require_owner,None)

    def test_server_logs_redact_room_and_capability_paths(self):
        from core.logging import PrivatePathFilter
        record=logging.LogRecord('uvicorn.error',20,'',0,'WebSocket %s',('/api/watch-together/rooms/private-room/ws',),None)
        PrivatePathFilter().filter(record)
        self.assertNotIn('private-room',record.getMessage())
        self.assertIn('[redacted]',record.getMessage())

    def test_openapi_marks_legacy_paths_and_error_contract(self):
        spec=app.openapi()
        self.assertEqual(spec['info']['version'],'1.0.0')
        self.assertTrue(spec['paths']['/api/catalog/search']['get']['deprecated'])
        self.assertIn('ErrorV1',spec['components']['schemas'])

    def test_delayed_control_reconnect_and_stale_host_candidate(self):
        now=[1000.]
        store=Rooms(clock=lambda:now[0])
        room,host=store.create(SimpleNamespace(id='a',profile_id=1),'A',Content(media_type='movie',tmdb_id=42))
        store.connect(room,host)
        guest=store.join(room,SimpleNamespace(id='b',profile_id=2),'B')
        store.connect(room,guest)
        delayed=Event(type='seek',revision=room.revision,position=8)
        store.apply(room,host,Event(type='play',revision=room.revision))
        now[0]+=.35
        with self.assertRaisesRegex(RoomError,'stale_revision'): store.apply(room,host,delayed)
        for _ in range(10):
            old=guest.connection
            store.connect(room,guest)
            store.disconnect(room,guest,old)
            self.assertIsNotNone(guest.connection)
        store.disconnect(room,host,host.connection)
        now[0]+=91
        store.cleanup()
        self.assertEqual(room.status,'closed')
        self.assertEqual(room.participants,{})
