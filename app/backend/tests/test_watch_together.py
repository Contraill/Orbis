import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select,func
from starlette.websockets import WebSocketDisconnect
from test_playback_hardening import HardeningTestCase,SequencedProvider,source
from watch_together.domain import Rooms,Policy,Content,Event,RoomError,rooms
from api.watch_together import connections
from db.models.profile import Profile
from db.models.foundation import ViewingProgress,ViewingDay
from db.models.playback import PlaybackState
from metadata.localization import store_metadata
from metadata.schemas import CatalogDetails,SeasonDetails,EpisodeSummary
from providers.manager import ResolutionFailed


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.
        self.store = Rooms(clock=lambda:self.now)
        self.a = SimpleNamespace(id='a',profile_id=1)
        self.b = SimpleNamespace(id='b',profile_id=2)
        self.room,self.host = self.store.create(self.a,'A',Content(media_type='movie',tmdb_id=42))
        self.store.connect(self.room,self.host)
        self.guest = self.store.join(self.room,self.b,'B')
        self.store.connect(self.room,self.guest)

    def event(self,type,**kw):
        return Event(type=type,revision=self.room.revision,**kw)

    def test_duplicate_join_authority_and_revision(self):
        revision = self.room.revision
        self.assertIs(self.store.join(self.room,self.b,'B'),self.guest)
        self.assertEqual(self.room.revision,revision)
        with self.assertRaisesRegex(RoomError,'host_only'):
            self.store.apply(self.room,self.guest,self.event('play'))
        self.store.apply(self.room,self.host,self.event('play'))
        with self.assertRaisesRegex(RoomError,'stale_revision'):
            self.store.apply(self.room,self.host,Event(type='pause',revision=revision))

    def test_play_pause_seek_and_clock(self):
        self.store.apply(self.room,self.host,self.event('seek',position=100.))
        self.store.apply(self.room,self.host,self.event('play'))
        self.now += 10
        self.assertEqual(self.store.position(self.room),110)
        self.store.apply(self.room,self.host,self.event('pause'))
        self.now += 5
        self.assertEqual(self.store.position(self.room),110)

    def test_drift_small_large_paused_and_unsupported_rate(self):
        self.store.apply(self.room,self.host,self.event('play',position=100.))
        for position,supported,expected in [(99.9,True,'none'),(99.,True,'rate'),(101.,True,'rate'),(97.,True,'seek'),(99.,False,'none')]:
            result=self.store.correction(self.room,position,supported)
            self.assertEqual(result['action'],expected)
            if expected=='rate': self.assertAlmostEqual(result['rate'],1.03 if position<100 else .97)
        self.store.apply(self.room,self.host,self.event('pause'))
        self.assertEqual(self.store.correction(self.room,99.9,False)['action'],'seek')
        self.assertEqual(self.store.correction(self.room,100.,False)['action'],'none')

    def test_disconnect_reconnect_grace_then_deterministic_promotion(self):
        original = self.host.connection
        self.store.disconnect(self.room,self.host,original)
        self.now+=44; self.store.cleanup()
        self.assertEqual(self.room.host,self.host.id)
        self.store.connect(self.room,self.host)
        self.store.disconnect(self.room,self.host,original)  # obsolete socket cannot disconnect replacement
        self.assertIsNotNone(self.host.connection)
        self.guest.last_seen = self.now
        self.store.disconnect(self.room,self.host,self.host.connection)
        self.now+=46; self.store.cleanup()
        self.assertEqual(self.room.host,self.guest.id)
        self.assertEqual(self.room.status,'open')

    def test_stale_cleanup_expiration_and_bounded_storage(self):
        self.now+=91; self.store.cleanup()
        self.assertTrue(all(p.connection is None for p in self.room.participants.values()))
        self.now+=46; self.store.cleanup()
        self.assertEqual(self.room.status,'closed')
        self.now+=61; self.store.cleanup()
        self.assertEqual(self.store.rooms,{})
        limited=Rooms(Policy(max_rooms=1),clock=lambda:self.now)
        r,p=limited.create(self.a,'A',Content(media_type='movie',tmdb_id=1))
        with self.assertRaisesRegex(RoomError,'room_capacity'):
            limited.create(self.b,'B',r.content)
        self.now+=1801; limited.cleanup()
        self.assertEqual(r.status,'closed')

    def test_leave_host_promotes_then_last_leave_closes(self):
        self.store.leave(self.room,self.host)
        self.assertEqual(self.room.host,self.guest.id)
        self.store.leave(self.room,self.guest)
        self.assertEqual(self.room.status,'closed')

    def test_host_disconnect_without_connected_successor_closes_after_grace(self):
        self.store.disconnect(self.room,self.guest,self.guest.connection)
        self.store.disconnect(self.room,self.host,self.host.connection)
        self.now+=44; self.store.cleanup()
        self.assertEqual(self.room.status,'open')
        self.now+=2; self.store.cleanup()
        self.assertEqual(self.room.status,'closed')

    def test_stale_heartbeat_does_not_shorten_host_disconnect_grace(self):
        self.now+=80
        self.store.disconnect(self.room,self.host,self.host.connection)
        self.guest.last_seen=self.now
        self.now+=20; self.store.cleanup()
        self.assertEqual(self.room.host,self.host.id)
        self.assertEqual(self.room.status,'open')
        self.now+=26; self.store.cleanup()
        self.assertEqual(self.room.host,self.guest.id)

    def test_participant_capacity_and_preferences_do_not_change_timeline(self):
        self.store.policy=Policy(max_participants=2)
        with self.assertRaisesRegex(RoomError,'participant_capacity'):
            self.store.join(self.room,SimpleNamespace(id='c',profile_id=3),'C')
        revision=self.room.revision
        self.store.apply(self.room,self.guest,self.event('preferences_changed'))
        self.assertGreater(self.room.revision,revision)
        self.assertEqual(self.room.content.key,'movie:42')
        self.assertEqual(self.room.position,0)

    def test_content_transition_resets_readiness_without_transport_data(self):
        self.store.apply(self.room,self.guest,self.event('ready'))
        target=Content(media_type='tv',tmdb_id=10,season_number=1,episode_number=1)
        self.store.apply(self.room,self.host,self.event('content',content=target))
        self.assertEqual(self.room.content.key,'tv:10:s1:e1')
        self.assertEqual(self.room.position,0)
        self.assertEqual(self.room.state,'paused')
        self.assertFalse(self.guest.ready)
        self.assertEqual(self.guest.previous_content.key,'movie:42')
        serialized=json.dumps(self.store.snapshot(self.room))
        for forbidden in ['session_id','source_session','url','headers','capabilities','provider']:
            self.assertNotIn(forbidden,serialized)

    def test_strict_payload_types(self):
        for payload in [dict(media_type='tv',tmdb_id=1),dict(media_type='movie',tmdb_id=0),dict(media_type='movie',tmdb_id=1,season_number=1),dict(media_type='movie',tmdb_id=True)]:
            with self.assertRaises(ValueError): Content(**payload)
        for payload in [dict(type='seek',revision=1),dict(type='seek',revision=1,position=float('nan')),dict(type='play',revision=1,url='secret'),dict(type='position',revision=1,position=-1),dict(type='close',revision='1')]:
            with self.assertRaises(ValueError): Event(**payload)


class RoomAPITests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        rooms.rooms.clear(); connections.clear()
        self.addCleanup(rooms.rooms.clear)
        self.addCleanup(connections.clear)
        self.other=Profile(name='Second')
        self.db.add(self.other); self.db.commit()
        self.a=self.register(self.profile.id)
        self.b=self.register(self.other.id)
        self.content={'media_type':'movie','tmdb_id':42}

    def register(self,profile):
        response=self.client.post('/api/sessions',json={'profile_id':profile,'display_name':'Browser'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def create(self,content=None):
        response=self.client.post('/api/watch-together/rooms',headers={'X-Orbis-Session':self.a},json={'content':content or self.content})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def join(self,room,session=None):
        return self.client.post(f'/api/watch-together/rooms/{room}/join',headers={'X-Orbis-Session':session or self.b})

    def open(self,ws,session):
        ws.send_json({'session_id':session})
        self.assertEqual(ws.receive_json()['type'],'welcome')
        return self.receive(ws,'state')

    def receive(self,ws,type,revision=None):
        for _ in range(20):
            value=ws.receive_json()
            if value['type']==type and (revision is None or value.get('revision',0)>=revision):
                return value
        self.fail('Expected socket message')

    def test_create_duplicate_join_invalid_and_cookie_isolation(self):
        room=self.create()['room_id']
        self.assertEqual(self.join(room).status_code,200)
        self.assertEqual(len(self.join(room).json()['participants']),2)
        self.assertEqual(self.join('missing').status_code,404)
        self.client.cookies.clear()
        self.assertEqual(self.join(room).status_code,404)

    def test_two_clients_play_pause_seek_reconnect_and_security(self):
        room=self.create()['room_id']; self.join(room)
        path=f'/api/watch-together/rooms/{room}/ws'
        with self.client:
            with self.client.websocket_connect(path) as host:
                self.open(host,self.a)
                with self.client.websocket_connect(path) as guest:
                    state=self.open(guest,self.b)
                    self.receive(host,'state',state['revision'])
                    guest.send_json({'type':'play','revision':state['revision']})
                    self.assertEqual(self.receive(guest,'error')['code'],'host_only')
                    host.send_json({'type':'play','revision':state['revision'],'position':100.})
                    playing=self.receive(host,'state',state['revision']+1)
                    self.assertEqual(self.receive(guest,'state',playing['revision'])['state'],'playing')
                    host.send_json({'type':'seek','revision':playing['revision'],'position':200.})
                    seek=self.receive(guest,'state',playing['revision']+1)
                    self.assertAlmostEqual(seek['position'],200,delta=1)
                    host.send_json({'type':'pause','revision':seek['revision']})
                    paused=self.receive(guest,'state',seek['revision']+1)
                    self.assertEqual(paused['state'],'paused')
                    guest.send_json({'type':'position','revision':paused['revision'],'position':10.})
                    self.assertEqual(self.receive(guest,'sync')['action'],'seek')
                    guest.send_json({'type':'ready','revision':paused['revision'],'provider_url':'secret'})
                    self.assertEqual(self.receive(guest,'error')['code'],'invalid_event')
                with self.client.websocket_connect(path) as rejoined:
                    restored=self.open(rejoined,self.b)
                    self.assertEqual(restored['state'],'paused')
                    self.assertAlmostEqual(restored['position'],paused['position'])
                    host.send_json({'type':'close','revision':restored['revision']})
                    self.assertEqual(self.receive(rejoined,'state',restored['revision']+1)['status'],'closed')

    def test_ws_membership_origin_and_oversize(self):
        room=self.create()['room_id']; path=f'/api/watch-together/rooms/{room}/ws'
        with self.client:
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(path,headers={'Origin':'https://evil.example'}) as ws:
                    ws.receive_json()
            with self.client.websocket_connect(path) as ws:
                ws.send_json({'session_id':self.b})
                with self.assertRaises(WebSocketDisconnect): ws.receive_json()
            with self.client.websocket_connect(path) as ws:
                self.open(ws,self.a)
                ws.send_text('x'*4097)
                with self.assertRaises(WebSocketDisconnect) as exc: ws.receive_json()
                self.assertEqual(exc.exception.code,1009)

    def test_independent_sources_resolution_failure_and_history(self):
        first=SequencedProvider('first',1,[[source('first','moly',protocol='http',quality='900p')]])
        second=SequencedProvider('second',2,[[source('second','dbx',protocol='http',quality='720p')]])
        for item in self.provider_patches([first,second]): item.start(); self.addCleanup(item.stop)
        # Participant B's own existing preferences select a different provider.
        root=f'/api/playback/profiles/{self.other.id}/movie/42'
        self.client.put(root+'/state',json={'preferred_provider_id':'second'})
        state=self.create(); room=state['room_id']; self.join(room)
        results=[]
        for session in (self.a,self.b):
            response=self.client.post(f'/api/watch-together/rooms/{room}/resolve',headers={'X-Orbis-Session':session},json={'content_revision':state['content_revision']})
            self.assertEqual(response.status_code,200,response.text)
            results.append(response.json()['playback'])
        self.assertEqual([r['selected_source']['provider_id'] for r in results],['first','second'])
        self.assertNotEqual(results[0]['source_session_id'],results[1]['source_session_id'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),0)
        before=rooms.snapshot(rooms.get(room))
        with patch('api.watch_together.playback_service.resolve',side_effect=ResolutionFailed([])):
            failed=self.client.post(f'/api/watch-together/rooms/{room}/resolve',headers={'X-Orbis-Session':self.b},json={'content_revision':state['content_revision']})
            self.assertEqual(failed.status_code,502,failed.text)
        self.assertEqual(rooms.get(room).revision,before['revision'])
        for session,profile,position in [(self.a,self.profile.id,30),(self.b,self.other.id,60)]:
            response=self.client.put(f'/api/playback/profiles/{profile}/movie/42/state',headers={'X-Orbis-Session':session},json={'position_seconds':position,'duration_seconds':1200})
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),2)
        self.assertEqual(self.db.scalar(select(func.sum(ViewingProgress.watched_seconds))),0)
        with rooms.lock:
            r=rooms.get(room); p=rooms.member(r,self.a)
            for _ in range(50): rooms.apply(r,p,Event(type='position',revision=r.revision,position=30.))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),2)
        self.assertEqual(self.db.scalar(select(func.sum(ViewingProgress.watched_seconds))),0)

    def test_revoked_session_and_binary_payload_rejected(self):
        room=self.create()['room_id']; path=f'/api/watch-together/rooms/{room}/ws'
        with self.client:
            with self.client.websocket_connect(path) as ws:
                self.open(ws,self.a)
                ws.send_bytes(b'not a text event')
                with self.assertRaises(WebSocketDisconnect) as exc: ws.receive_json()
                self.assertEqual(exc.exception.code,1003)
            self.client.delete('/api/sessions/'+self.a)
            with self.client.websocket_connect(path) as ws:
                ws.send_json({'session_id':self.a})
                with self.assertRaises(WebSocketDisconnect) as exc: ws.receive_json()
                self.assertEqual(exc.exception.code,1008)
    def test_next_episode_and_season_boundary_no_history(self):
        store_metadata(self.db,'en-US',CatalogDetails(tmdb_id=42,media_type='tv',title='Series',status='Ended',seasons=[{'tmdb_id':1,'season_number':1,'name':'One','episode_count':2},{'tmdb_id':2,'season_number':2,'name':'Two','episode_count':1}]))
        for number,count in [(1,2),(2,1)]:
            store_metadata(self.db,'en-US',SeasonDetails(series_tmdb_id=42,season_tmdb_id=number,season_number=number,name='Season',episodes=[EpisodeSummary(tmdb_id=number*10+i,episode_number=i,name='Episode',air_date='2020-01-01') for i in range(1,count+1)]))
        self.db.commit()
        room=self.create({'media_type':'tv','tmdb_id':42,'season_number':1,'episode_number':1})['room_id']
        with self.client, self.client.websocket_connect(f'/api/watch-together/rooms/{room}/ws') as host:
            state=self.open(host,self.a)
            for season,episode in [(1,2),(2,1)]:
                host.send_json({'type':'next_episode','revision':state['revision']})
                state=self.receive(host,'state',state['revision']+1)
                self.assertEqual((state['content']['season_number'],state['content']['episode_number']),(season,episode))
                self.assertEqual(state['state'],'paused')
            host.send_json({'type':'next_episode','revision':state['revision']})
            self.assertEqual(self.receive(host,'error')['code'],'next_episode_unavailable')
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PlaybackState)),0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),0)

    def test_transition_during_private_resolution_rejects_stale_result(self):
        provider=SequencedProvider('first',1,[[source('first','own',protocol='http',quality='720p')]])
        for item in self.provider_patches([provider]): item.start(); self.addCleanup(item.stop)
        state=self.create(); room=rooms.get(state['room_id'])
        async def transition_during_fetch(*args):
            with rooms.lock:
                rooms.apply(room,rooms.member(room,self.a),Event(type='content',revision=room.revision,content=Content(media_type='movie',tmdb_id=43)))
            return provider.next_sources()
        with patch.object(provider,'resolve_movie',side_effect=transition_during_fetch):
            response=self.client.post(f'/api/watch-together/rooms/{room.id}/resolve',headers={'X-Orbis-Session':self.a},json={'content_revision':state['content_revision']})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['detail']['code'],'stale_content')
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),0)
        self.assertIsNone(self.client.get('/api/sessions/'+self.a).json()['current_playback'])
