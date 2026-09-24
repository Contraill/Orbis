"""Room messages contain intent only. Media is resolved through a private HTTP response."""
import asyncio
from contextlib import asynccontextmanager
from time import monotonic
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session
from db.session import get_db
from db.models.profile import Profile, utc_now
from db.models.client_session import ClientSession
from client_sessions.service import require
from playback.capabilities import request_client
from playback.episodes import lifecycle, preferences
from playback.service import ContentIdentity, get_playback_state, playback_service
from playback.source_sessions import source_sessions
from providers.manager import ResolutionFailed
from api.playback import _resolution_failed
from watch_together.domain import rooms, RoomError, Content, Event

router = APIRouter(prefix='/api/watch-together',tags=['watch together'])
MAX_MESSAGE_BYTES = 4096


class CreateRoom(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: Content
    position: float = Field(default=0,ge=0,le=604800,allow_inf_nan=False)


class Authenticate(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    session_id: str = Field(min_length=32,max_length=64)


class ResolveRoom(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    content_revision: int = Field(ge=1)


# One bounded outgoing queue per connection. Only the sender writes the socket.
connections = {}


def enqueue(queue, message):
    if queue.full():
        # Full snapshots supersede old snapshots; a slow client never blocks a room.
        while not queue.empty():
            queue.get_nowait()
    queue.put_nowait(message)


def broadcast(room):
    message = rooms.snapshot(room)
    for (room_id,_), (_,queue) in list(connections.items()):
        if room_id == room.id:
            enqueue(queue,message)


def fail(exc):
    return HTTPException(exc.status,{'code':exc.code})


def client(request: Request, db: Session = Depends(get_db)):
    return require(db,request.headers.get('X-Orbis-Session',''),request.cookies.get('playback_client',''))


def identity(content):
    return ContentIdentity(content.media_type,content.tmdb_id,content.season_number,content.episode_number)


def sweep():
    before = {r.id:r.revision for r in rooms.rooms.values()}
    rooms.cleanup()
    for room in rooms.rooms.values():
        if before.get(room.id) != room.revision:
            broadcast(room)


@asynccontextmanager
async def room_lifespan(app):
    async def janitor():
        while True:
            await asyncio.sleep(5)
            with rooms.lock:
                sweep()
    task = asyncio.create_task(janitor())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def receive_text(ws):
    message = await ws.receive()
    if message['type'] == 'websocket.disconnect':
        raise WebSocketDisconnect(message.get('code',1000))
    if message.get('text') is None:
        await ws.close(code=1003)
        raise WebSocketDisconnect(1003)
    return message['text']


@router.post('/rooms',status_code=201)
async def create(payload: CreateRoom, row=Depends(client), db: Session=Depends(get_db)):
    with rooms.lock:
        try:
            sweep()
            if any(r.status == 'open' and any(p.session_id == row.id for p in r.participants.values()) for r in rooms.rooms.values()):
                raise RoomError('session_already_in_room')
            room,p = rooms.create(row,db.get(Profile,row.profile_id).name,payload.content,payload.position)
            return {**rooms.snapshot(room),'participant_id':p.id}
        except RoomError as exc:
            raise fail(exc)


@router.post('/rooms/{room_id}/join')
async def join(room_id: str, row=Depends(client),db: Session=Depends(get_db)):
    with rooms.lock:
        try:
            sweep()
            room = rooms.get(room_id)
            p = rooms.join(room,row,db.get(Profile,row.profile_id).name)
            broadcast(room)
            return {**rooms.snapshot(room),'participant_id':p.id}
        except RoomError as exc:
            raise fail(exc)


@router.get('/rooms/{room_id}')
async def current(room_id: str,row=Depends(client)):
    with rooms.lock:
        try:
            sweep()
            room = rooms.get(room_id,False)
            p = rooms.member(room,row.id)
            return {**rooms.snapshot(room),'participant_id':p.id}
        except RoomError as exc:
            raise fail(exc)


@router.post('/rooms/{room_id}/resolve')
async def resolve(room_id: str,payload: ResolveRoom,row=Depends(client),db: Session=Depends(get_db)):
    with rooms.lock:
        try:
            sweep()
            room = rooms.get(room_id)
            p = rooms.member(room,row.id)
            if room.content_revision != payload.content_revision:
                raise RoomError('stale_content')
            content, previous = room.content, p.previous_content
        except RoomError as exc:
            raise fail(exc)
    ctx = {'id':row.id,'capabilities':row.capabilities}
    token = request_client.set(ctx)
    try:
        inherited = preferences(get_playback_state(db,row.profile_id,identity(previous))) if previous else None
        result = await playback_service.resolve(db,row.profile_id,identity(content),audience=row.audience,inherited_preferences=inherited)
        with rooms.lock:
            try:
                current_room = rooms.get(room_id)
                rooms.member(current_room,row.id)
                if current_room.content_revision != payload.content_revision:
                    raise RoomError('stale_content')
                row = db.get(ClientSession,row.id,populate_existing=True)
                if row is None or row.revoked_at:
                    raise RoomError('session_revoked',403)
            except RoomError as exc:
                source_sessions.discard(result.source_session_id)
                raise fail(exc)
            source, canonical = ctx['resolved']
            row.current_playback, row.source_session_id = canonical,source.session_id
            row.state, row.last_seen, row.position_seconds = 'preparing',utc_now(),result.state.position_seconds
            row.started_at, row.stopped_at = None,None
            db.commit()
            p.resolved_content, p.previous_content = content,None
        return {'playback':result,'room':rooms.snapshot(current_room)}
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)
    finally:
        request_client.reset(token)


def next_episode(room,profile_id,db):
    if room.content.media_type != 'tv':
        raise RoomError('not_a_series')
    target = lifecycle(db,profile_id,identity(room.content))['next']
    if not target or not target['aired']:
        raise RoomError('next_episode_unavailable')
    return Content(media_type='tv',tmdb_id=target['tmdb_id'],season_number=target['season_number'],episode_number=target['episode_number'])


async def send_messages(ws,queue):
    while True:
        await asyncio.wait_for(ws.send_json(await queue.get()),timeout=5)


@router.websocket('/rooms/{room_id}/ws')
async def socket(ws: WebSocket,room_id: str):
    origin = ws.headers.get('origin')
    if origin and (urlsplit(origin).scheme not in ('http','https') or urlsplit(origin).netloc != ws.headers.get('host')):
        await ws.close(code=1008)
        return
    await ws.accept()
    sender = None
    p = room = connection = None
    queue = asyncio.Queue(maxsize=16)
    # Use short-lived DB sessions even across arbitrarily long WebSocket lifetimes.
    def database():
        factory = ws.app.dependency_overrides.get(get_db,get_db)
        return factory()
    try:
        raw = await asyncio.wait_for(receive_text(ws),timeout=10)
        if len(raw.encode()) > MAX_MESSAGE_BYTES:
            await ws.close(code=1009)
            return
        auth = Authenticate.model_validate_json(raw)
        gen = database()
        db = next(gen)
        try:
            row = require(db,auth.session_id,ws.cookies.get('playback_client',''))
            with rooms.lock:
                sweep()
                room = rooms.get(room_id)
                p = rooms.member(room,row.id)
                connection = rooms.connect(room,p)
                old = connections.get((room.id,p.id))
                if old:
                    enqueue(old[1],{'type':'replaced'})
                connections[(room.id,p.id)] = (connection,queue)
                enqueue(queue,{'type':'welcome','participant_id':p.id})
                broadcast(room)
        finally:
            gen.close()
        sender = asyncio.create_task(send_messages(ws,queue))
        allowance, last = 20.,monotonic()
        while True:
            try:
                raw = await asyncio.wait_for(receive_text(ws),timeout=5)
            except asyncio.TimeoutError:
                raw = None
            with rooms.lock:
                sweep()
                if room.status != 'open' or p.id not in room.participants or p.connection != connection:
                    break
            if sender.done():
                break
            gen = database()
            db = next(gen)
            try:
                row = require(db,auth.session_id,ws.cookies.get('playback_client',''))
                if raw is None:
                    continue
                now = monotonic()
                allowance = min(20.,allowance+(now-last)*10)
                last = now
                if allowance < 1:
                    await ws.close(code=1008)
                    break
                allowance -= 1
                if len(raw.encode()) > MAX_MESSAGE_BYTES:
                    await ws.close(code=1009)
                    break
                try:
                    event = Event.model_validate_json(raw)
                    with rooms.lock:
                        if event.type == 'next_episode' and p.id != room.host:
                            raise RoomError('host_only',403)
                        target = next_episode(room,p.profile_id,db) if event.type == 'next_episode' else None
                        result = rooms.apply(room,p,event,target)
                        if event.type == 'position':
                            enqueue(queue,result)
                        else:
                            broadcast(room)
                        if (utc_now()-row.last_seen).total_seconds() >= 20:
                            row.last_seen = utc_now()
                            db.commit()
                except ValidationError:
                    enqueue(queue,{'type':'error','code':'invalid_event'})
                except RoomError as exc:
                    enqueue(queue,{'type':'error','code':exc.code,'revision':room.revision})
                    enqueue(queue,rooms.snapshot(room))
            finally:
                gen.close()
    except (ValidationError,HTTPException,RoomError):
        await ws.close(code=1008)
    except (WebSocketDisconnect,asyncio.TimeoutError,RuntimeError):
        pass
    finally:
        if sender:
            sender.cancel()
            await asyncio.gather(sender,return_exceptions=True)
        if room and p and connection:
            with rooms.lock:
                existing = connections.get((room.id,p.id))
                if existing and existing[0] == connection:
                    connections.pop((room.id,p.id),None)
                if p.id in room.participants:
                    rooms.disconnect(room,p,connection)
                    broadcast(room)
        try:
            await ws.close()
        except (RuntimeError,WebSocketDisconnect):
            pass
