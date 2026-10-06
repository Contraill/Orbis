"""Bounded single-process coordination. No transport URLs or watch history live here."""
from dataclasses import dataclass, field
from secrets import randbelow, token_urlsafe
from threading import RLock
from time import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class Policy:
    max_rooms: int = 32
    max_participants: int = 8
    participant_stale: float = 60
    idle_ttl: float = 1800
    room_ttl: float = 21600
    closed_ttl: float = 60
    jitter: float = .25
    seek_threshold: float = 2
    paused_tolerance: float = .05
    correction_rate: float = .03
    correction_seconds: float = 5
    max_position: float = 604800


class Content(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    media_type: Literal['movie', 'tv']
    tmdb_id: int = Field(gt=0)
    season_number: int | None = Field(default=None, ge=0)
    episode_number: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def episode(self):
        if self.media_type == 'movie' and (self.season_number is not None or self.episode_number is not None):
            raise ValueError('Movie cannot have an episode')
        if self.media_type == 'tv' and (self.season_number is None or self.episode_number is None):
            raise ValueError('TV requires season and episode')
        return self

    @property
    def key(self):
        return f'movie:{self.tmdb_id}' if self.media_type == 'movie' else f'tv:{self.tmdb_id}:s{self.season_number}:e{self.episode_number}'


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    type: Literal['heartbeat', 'ready', 'play', 'pause', 'seek', 'position', 'content', 'next_episode', 'leave', 'preferences_changed']
    revision: int = Field(ge=1)
    content: Content | None = None
    position: float | None = Field(default=None, ge=0, le=604800, allow_inf_nan=False)
    rate_supported: bool = True

    @model_validator(mode='after')
    def fields_for_type(self):
        if (self.type == 'content') != (self.content is not None):
            raise ValueError('Content is required only for content transition')
        if self.type in ('seek', 'position') and self.position is None:
            raise ValueError('Position required')
        if self.position is not None and self.type not in ('seek', 'position', 'play', 'pause', 'content'):
            raise ValueError('Unexpected position')
        return self


class RoomError(ValueError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class Participant:
    id: str
    session_id: str
    profile_id: int
    name: str
    joined: float
    last_seen: float
    connection: str | None = None
    disconnected: float | None = None
    ready: bool = False
    # Used only by the private resolve endpoint to inherit this participant's preferences.
    previous_content: Content | None = None
    resolved_content: Content | None = None


@dataclass
class Room:
    id: str
    host: str
    content: Content | None
    created: float
    last_activity: float
    anchor_at: float
    position: float = 0
    state: str = 'paused'
    rate: float = 1
    revision: int = 1
    content_revision: int = 1
    status: str = 'open'
    closed_at: float | None = None
    participants: dict = field(default_factory=dict)
    join_code: str = ''
    creator: str = ''


class Rooms:
    def __init__(self, policy=Policy(), clock=time):
        self.policy, self.clock = policy, clock
        self.rooms = {}
        self.codes = {}
        self.lock = RLock()

    def position(self, room, now=None):
        now = self.clock() if now is None else now
        return min(self.policy.max_position, room.position + (max(0, now-room.anchor_at)*room.rate if room.state == 'playing' else 0))

    def bump(self, room):
        room.revision += 1
        room.last_activity = self.clock()

    def get(self, room_id, open_only=True):
        room = self.rooms.get(room_id)
        if not room:
            raise RoomError('room_not_found',404)
        if open_only and room.status != 'open':
            raise RoomError('room_closed',410)
        return room

    def member(self, room, session_id):
        participant = next((p for p in room.participants.values() if p.session_id == session_id),None)
        if not participant:
            raise RoomError('not_a_participant',403)
        return participant

    def create(self, session, name, content, position=0):
        self.cleanup()
        if len(self.rooms) >= self.policy.max_rooms:
            raise RoomError('room_capacity',429)
        now = self.clock()
        p = Participant(token_urlsafe(18),session.id,session.profile_id,name,now,now,disconnected=now)
        for _ in range(100):
            code = f'{randbelow(900000) + 100000:06d}'
            if code not in self.codes:
                break
        else:
            raise RoomError('room_capacity',429)
        room = Room(token_urlsafe(24),p.id,content,now,now,now,position=position,
                    content_revision=1 if content else 0,participants={p.id:p},join_code=code,creator=p.id)
        self.rooms[room.id] = room
        self.codes[code] = room.id
        return room, p

    def by_code(self, code):
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise RoomError('invalid_join_code',404)
        room_id = self.codes.get(code)
        if not room_id:
            raise RoomError('invalid_join_code',404)
        try:
            return self.get(room_id)
        except RoomError:
            raise RoomError('invalid_join_code',404)

    def join(self, room, session, name):
        for existing in self.rooms.values():
            if existing.status == 'open' and existing.id != room.id and any(p.session_id == session.id for p in existing.participants.values()):
                raise RoomError('session_already_in_room')
        existing = next((p for p in room.participants.values() if p.session_id == session.id),None)
        if existing:
            existing.last_seen = self.clock()
            return existing
        if len(room.participants) >= self.policy.max_participants:
            raise RoomError('participant_capacity',429)
        now = self.clock()
        p = Participant(token_urlsafe(18),session.id,session.profile_id,name,now,now,disconnected=now)
        room.participants[p.id] = p
        self.bump(room)
        return p

    def connect(self, room, p):
        p.connection, p.disconnected, p.last_seen = token_urlsafe(16), None, self.clock()
        p.ready = False
        self.bump(room)
        return p.connection

    def disconnect(self, room, p, connection, disconnected_at=None):
        if p.connection != connection:
            return
        p.connection, p.disconnected, p.ready = None, self.clock() if disconnected_at is None else disconnected_at, False
        self.bump(room)

    def close(self, room):
        room.position, room.anchor_at = self.position(room), self.clock()
        room.state, room.status, room.closed_at = 'paused', 'closed', self.clock()
        self.codes.pop(room.join_code,None)
        self.bump(room)

    def leave(self, room, p):
        room.participants.pop(p.id,None)
        if not room.participants:
            self.close(room)
            return
        if room.host == p.id:
            room.host = min(room.participants.values(),key=lambda member:(member.joined,member.id)).id
        self.bump(room)

    def cleanup(self):
        now = self.clock()
        for room in list(self.rooms.values()):
            if room.status == 'closed':
                if now-room.closed_at >= self.policy.closed_ttl:
                    del self.rooms[room.id]
                continue
            if now-room.created >= self.policy.room_ttl or now-room.last_activity >= self.policy.idle_ttl:
                self.close(room)
                continue
            for p in list(room.participants.values()):
                if p.connection and now-p.last_seen >= self.policy.participant_stale:
                    self.disconnect(room,p,p.connection,p.last_seen)
                if p.connection is None and p.disconnected is not None and now-p.disconnected >= self.policy.participant_stale:
                    self.leave(room,p)

    def snapshot(self, room):
        return {'type':'state','room_id':room.id,'join_code':room.join_code,'revision':room.revision,'content_revision':room.content_revision,
            'content':room.content.model_dump() if room.content else None,'content_key':room.content.key if room.content else None,'host_id':room.host,'status':room.status,
            'state':room.state,'position':self.position(room),'rate':room.rate,'server_time':self.clock(),
            'created_at':room.created,'last_activity':room.last_activity,
            'participants':[{'id':p.id,'profile_id':p.profile_id,'name':p.name,'connected':p.connection is not None,'ready':p.ready} for p in room.participants.values()]}

    def correction(self, room, position, supported):
        if room.content is None:
            raise RoomError('room_waiting_for_content')
        target = self.position(room)
        drift = target-position
        if room.state == 'paused':
            action = 'seek' if abs(drift)>self.policy.paused_tolerance else 'none'
        else:
            action = 'seek' if abs(drift)>=self.policy.seek_threshold else 'rate' if supported and abs(drift)>self.policy.jitter else 'none'
        rate = room.rate + (self.policy.correction_rate if drift>0 else -self.policy.correction_rate) if action == 'rate' else room.rate
        return {'type':'sync','revision':room.revision,'content_revision':room.content_revision,'position':target,'state':room.state,
            'action':action,'rate':rate,'duration':self.policy.correction_seconds,'drift':drift}

    def apply(self, room, p, event, next_content=None):
        if event.revision != room.revision:
            raise RoomError('stale_revision')
        p.last_seen = self.clock()
        if event.type == 'heartbeat':
            room.last_activity = self.clock()
            return self.snapshot(room)
        if event.type == 'position':
            if room.content is None:
                raise RoomError('room_waiting_for_content')
            room.last_activity = self.clock()
            return self.correction(room,event.position,event.rate_supported)
        if event.type == 'ready':
            if not p.ready:
                p.ready = True
                self.bump(room)
        elif event.type == 'preferences_changed':
            # A private provider/quality re-resolution never changes shared content.
            p.ready = False
            self.bump(room)
        elif event.type in ('play','pause','seek'):
            if room.content is None:
                raise RoomError('room_waiting_for_content')
            room.position = self.position(room) if event.position is None else event.position
            room.anchor_at = self.clock()
            if event.type != 'seek':
                room.state = 'playing' if event.type == 'play' else 'paused'
            self.bump(room)
        elif event.type in ('content','next_episode'):
            target = event.content or next_content
            if target is None:
                raise RoomError('next_episode_unavailable')
            for participant in room.participants.values():
                participant.previous_content = participant.resolved_content or room.content
                participant.ready = False
            room.content, room.position, room.anchor_at, room.state = target, event.position or 0, self.clock(), 'paused'
            self.bump(room)
            room.content_revision = room.revision
        elif event.type == 'leave':
            self.leave(room,p)
        return self.snapshot(room)


rooms = Rooms()
