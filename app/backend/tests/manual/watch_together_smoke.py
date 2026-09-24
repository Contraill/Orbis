"""Two independent network clients through the production nginx WS proxy.

Run inside the disposable smoke backend's network namespace. No external media.
"""
import asyncio
import json
import sqlite3
import httpx
import websockets

BASE='http://127.0.0.1'

async def response(client,method,path,**kwargs):
    result=await client.request(method,BASE+path,**kwargs)
    result.raise_for_status()
    return result.json()

async def receive(ws,type,revision=0):
    async with asyncio.timeout(5):
        while True:
            event=json.loads(await ws.recv())
            if event['type']==type and event.get('revision',revision)>=revision:
                return event

async def connect(client,session,room):
    cookie='; '.join(f'{k}={v}' for k,v in client.cookies.items())
    ws=await websockets.connect(f'ws://127.0.0.1/api/watch-together/rooms/{room}/ws',additional_headers={'Cookie':cookie},origin=BASE)
    await ws.send(json.dumps({'session_id':session}))
    await receive(ws,'welcome')
    state=await receive(ws,'state')
    return ws,state

async def main():
    async with httpx.AsyncClient() as a,httpx.AsyncClient() as b:
        front=await a.get(BASE+'/')
        assert front.status_code==200 and '<div id="root">' in front.text
        for client,profile in [(a,1),(b,2)]:
            session=await response(client,'POST','/api/sessions',json={'profile_id':profile,'display_name':f'Network client {profile}'})
            client.headers['X-Orbis-Session']=session['id']
        assert a.cookies.get('playback_client') != b.cookies.get('playback_client')
        state=await response(a,'POST','/api/watch-together/rooms',json={'content':{'media_type':'tv','tmdb_id':42,'season_number':1,'episode_number':1},'position':12})
        room=state['room_id']; root=f'/api/watch-together/rooms/{room}'
        await response(b,'POST',root+'/join')
        host,_=await connect(a,a.headers['X-Orbis-Session'],room)
        guest,_=await connect(b,b.headers['X-Orbis-Session'],room)
        async def resolve_both():
            state=await response(a,'GET',root)
            own=[]
            for client in (a,b):
                value=await response(client,'POST',root+'/resolve',json={'content_revision':state['content_revision']})
                own.append(value['playback'])
            assert [s['selected_source']['provider_id'] for s in own]==['smoke-a','smoke-b']
            assert own[0]['source_session_id'] != own[1]['source_session_id']
            serialized=json.dumps(state)
            assert all(s['selected_source']['url'] not in serialized for s in own)
            assert 'source_session_id' not in serialized and 'provider_id' not in serialized
            return own
        async def control(type,**fields):
            current=await response(a,'GET',root)
            await host.send(json.dumps({'type':type,'revision':current['revision'],**fields}))
            return await receive(guest,'state',current['revision']+1)
        await resolve_both()
        assert (await control('play'))['state']=='playing'
        seek=await control('seek',position=120.)
        assert abs(seek['position']-120)<1
        paused=await control('pause')
        await guest.close()
        guest,restored=await connect(b,b.headers['X-Orbis-Session'],room)
        assert restored['state']=='paused' and abs(restored['position']-paused['position'])<.1
        for season,episode in [(1,2),(2,1)]:
            state=await control('next_episode')
            assert (state['content']['season_number'],state['content']['episode_number'])==(season,episode)
            await resolve_both()
        with sqlite3.connect('/tmp/orbis-watch-smoke.db') as db:
            assert db.execute('select count(*) from viewing_progress').fetchone()[0]==0
        for client,profile,position in [(a,1,30),(b,2,60)]:
            await response(client,'PUT',f'/api/playback/profiles/{profile}/tv/42/season/2/episode/1/state',json={'position_seconds':position,'duration_seconds':1200})
        with sqlite3.connect('/tmp/orbis-watch-smoke.db') as db:
            assert db.execute('select profile_id from viewing_progress order by profile_id').fetchall()==[(1,),(2,)]
        state=await response(b,'GET',root)
        await guest.send(json.dumps({'type':'leave','revision':state['revision']}))
        await receive(host,'state',state['revision']+1)
        state=await response(a,'GET',root)
        await host.send(json.dumps({'type':'close','revision':state['revision']}))
        assert (await receive(host,'state',state['revision']+1))['status']=='closed'
        await guest.close(); await host.close()
        print('PASS: nginx HTTP/WS upgrade; separate cookies/profiles/sources; play/pause/seek; reconnect; episode/season transitions; isolated history; leave/close; no transport secrets in room snapshots.')

asyncio.run(main())
