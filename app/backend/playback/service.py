from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.playback import (
    PlaybackState,
    playback_content_key,
)
from db.models.profile import Profile
from playback.matching import selections_for_source
from playback.delivery import delivery_broker
from playback.source_sessions import source_sessions
from playback.choices import ranked_choices, set_session_choices, selected_height, quality_result
from playback.schemas import (
    MediaType,
    PlaybackClientSource,
    PlaybackResolutionSummary,
    PlaybackSession,
    PlaybackStateUpdate,
    PlaybackStateView,
    PlaybackPreferences,
    PlaybackChoices,
)
from playback.capabilities import current_capabilities, request_client, ClientCompatibilityError
from providers.manager import ProviderManager, provider_manager
from providers.source_policy import (
    aware_utc,
    source_expiry_status,
    source_refresh_at,
)


MIN_PROGRESS_SECONDS = 5.0
COMPLETION_REMAINING_SECONDS = 10.0


class ProfileNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ContentIdentity:
    media_type: MediaType
    tmdb_id: int
    season_number: int | None = None
    episode_number: int | None = None

    @property
    def content_key(self) -> str:
        return playback_content_key(
            self.media_type,
            self.tmdb_id,
            self.season_number,
            self.episode_number,
        )


def movie_identity(tmdb_id: int) -> ContentIdentity:
    return ContentIdentity(
        media_type="movie",
        tmdb_id=tmdb_id,
    )


def episode_identity(
    tmdb_id: int,
    season_number: int,
    episode_number: int,
) -> ContentIdentity:
    return ContentIdentity(
        media_type="tv",
        tmdb_id=tmdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )


def _require_profile(db: Session, profile_id: int) -> None:
    if db.get(Profile, profile_id) is None:
        raise ProfileNotFoundError(profile_id)


def get_playback_state(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    *,
    require_profile: bool = True,
) -> PlaybackState | None:
    if require_profile:
        _require_profile(db, profile_id)

    return db.scalar(
        select(PlaybackState).where(
            PlaybackState.profile_id == profile_id,
            PlaybackState.content_key == identity.content_key,
        )
    )


def list_playback_states(
    db: Session,
    profile_id: int,
) -> list[PlaybackState]:
    _require_profile(db, profile_id)
    return list(
        db.scalars(
            select(PlaybackState)
            .where(PlaybackState.profile_id == profile_id)
            .order_by(
                PlaybackState.updated_at.desc(),
                PlaybackState.id.desc(),
            )
        ).all()
    )


def _normalized_progress(
    update: PlaybackStateUpdate,
) -> tuple[float, bool]:
    position = update.position_seconds
    completed = update.completed

    if update.duration_seconds is not None:
        position = min(position, update.duration_seconds)
        if (
            position >= MIN_PROGRESS_SECONDS
            and position / update.duration_seconds >= 0.9
            and update.duration_seconds - position
            <= COMPLETION_REMAINING_SECONDS
        ):
            completed = True

    if completed or position < MIN_PROGRESS_SECONDS:
        position = 0.0

    return position, completed


def _apply_update(
    state: PlaybackState,
    update: PlaybackStateUpdate,
) -> None:
    position, completed = _normalized_progress(update)
    state.position_seconds = position
    state.duration_seconds = update.duration_seconds
    state.completed = completed
    state.last_provider_id = update.last_provider_id
    state.preferred_audio_language = (
        update.preferred_audio_language
    )
    state.preferred_audio_kind = update.preferred_audio_kind
    state.subtitles_enabled = update.subtitles_enabled
    state.preferred_subtitle_language = (
        update.preferred_subtitle_language
    )
    for name in PlaybackPreferences.model_fields:
        # Old clients saving progress must not silently reset newer preferences.
        if name in update.model_fields_set:
            setattr(state, name, getattr(update, name))


def upsert_playback_state(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    update: PlaybackStateUpdate,
    *,
    record_activity: bool = False,
) -> PlaybackState:
    if record_activity and db.bind.dialect.name == "sqlite" and not db.in_transaction():
        # Serialize the read/modify/write of resume + evidence, including first saves.
        db.execute(text("BEGIN IMMEDIATE"))
    _require_profile(db, profile_id)
    state = get_playback_state(
        db,
        profile_id,
        identity,
        require_profile=False,
    )

    if state is None:
        state = PlaybackState(
            profile_id=profile_id,
            content_key=identity.content_key,
            media_type=identity.media_type,
            tmdb_id=identity.tmdb_id,
            season_number=identity.season_number,
            episode_number=identity.episode_number,
        )
        db.add(state)

    if record_activity:
        from activity.service import record_progress
        record_progress(db, profile_id, identity, update)
    _apply_update(state, update)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        state = get_playback_state(
            db,
            profile_id,
            identity,
            require_profile=False,
        )
        if state is None:
            raise
        if record_activity:
            record_progress(db, profile_id, identity, update)
        _apply_update(state, update)
        db.commit()

    db.refresh(state)
    return state


def state_view(state: PlaybackState) -> PlaybackStateView:
    return PlaybackStateView(
        profile_id=state.profile_id,
        media_type=state.media_type,
        tmdb_id=state.tmdb_id,
        season_number=state.season_number,
        episode_number=state.episode_number,
        position_seconds=state.position_seconds,
        duration_seconds=state.duration_seconds,
        completed=state.completed,
        last_provider_id=state.last_provider_id,
        preferred_audio_language=(
            state.preferred_audio_language
        ),
        preferred_audio_kind=state.preferred_audio_kind,
        subtitles_enabled=state.subtitles_enabled,
        preferred_subtitle_language=(
            state.preferred_subtitle_language
        ),
        resume_position_seconds=(
            0.0
            if state.completed
            else state.position_seconds
        ),
        updated_at=state.updated_at,
        **{name: getattr(state, name) for name in PlaybackPreferences.model_fields},
    )


class PlaybackService:
    def __init__(
        self,
        manager: ProviderManager = provider_manager,
    ) -> None:
        self.manager = manager

    async def resolve(
        self,
        db: Session,
        profile_id: int,
        identity: ContentIdentity,
        *,
        excluded_provider_ids: set[str] | None = None,
        require_healthy_source: bool = False,
        preferred_audio_track_id: str | None = None,
        preferred_subtitle_track_id: str | None = None,
        audience: str = "",
        prepare: bool = False,
        inherited_preferences: dict | None = None,
    ) -> PlaybackSession:
        state = get_playback_state(
            db,
            profile_id,
            identity,
        )
        if inherited_preferences:
            from types import SimpleNamespace
            from db.models.profile import utc_now
            profile = db.get(Profile, profile_id)
            values = state_view(state).model_dump() if state else dict(
                profile_id=profile_id, media_type=identity.media_type, tmdb_id=identity.tmdb_id,
                season_number=identity.season_number, episode_number=identity.episode_number,
                position_seconds=0, duration_seconds=None, completed=False, last_provider_id=None,
                preferred_audio_language=profile.preferred_audio_language, preferred_audio_kind=None,
                preferred_subtitle_language=profile.preferred_subtitle_language, subtitles_enabled=profile.subtitles_enabled,
                updated_at=utc_now(), **PlaybackPreferences().model_dump())
            values.update(inherited_preferences)
            state = SimpleNamespace(**values)
        preferred_provider_id = (
            state.preferred_provider_id or state.last_provider_id
            if state is not None
            else None
        )

        if identity.media_type == "movie":
            resolution = await self.manager.resolve_movie(
                db,
                identity.tmdb_id,
                preferred_provider_id=preferred_provider_id,
                excluded_provider_ids=excluded_provider_ids,
                require_healthy_source=require_healthy_source,
            )
        else:
            if (
                identity.season_number is None
                or identity.episode_number is None
            ):
                raise ValueError(
                    "Episode identity requires season and episode numbers"
                )
            resolution = await self.manager.resolve_episode(
                db,
                identity.tmdb_id,
                identity.season_number,
                identity.episode_number,
                preferred_provider_id=preferred_provider_id,
                excluded_provider_ids=excluded_provider_ids,
                require_healthy_source=require_healthy_source,
            )

        if state is None:
            profile = db.get(Profile, profile_id)
            update = PlaybackStateUpdate(
                preferred_audio_language=profile.preferred_audio_language,
                preferred_subtitle_language=profile.preferred_subtitle_language,
                subtitles_enabled=profile.subtitles_enabled,
                last_provider_id=(
                    resolution.selected_provider_id
                )
            )
        else:
            update = PlaybackStateUpdate(
                position_seconds=state.position_seconds,
                duration_seconds=state.duration_seconds,
                completed=state.completed,
                last_provider_id=(
                    resolution.selected_provider_id
                ),
                preferred_audio_language=(
                    state.preferred_audio_language
                ),
                preferred_audio_kind=(
                    state.preferred_audio_kind
                ),
                subtitles_enabled=state.subtitles_enabled,
                preferred_subtitle_language=(
                    state.preferred_subtitle_language
                ),
                **{name: getattr(state, name) for name in PlaybackPreferences.model_fields},
            )

        if prepare:
            from types import SimpleNamespace
            from db.models.profile import utc_now
            state = SimpleNamespace(profile_id=profile_id, content_key=identity.content_key,
                media_type=identity.media_type, tmdb_id=identity.tmdb_id,
                season_number=identity.season_number, episode_number=identity.episode_number,
                updated_at=utc_now(), **update.model_dump())
        else:
            state = upsert_playback_state(db, profile_id, identity, update)
        stable_audio_track_id = (
            preferred_audio_track_id
            if resolution.selected_provider_id
            == preferred_provider_id
            else None
        )
        stable_subtitle_track_id = (
            preferred_subtitle_track_id
            if resolution.selected_provider_id
            == preferred_provider_id
            else None
        )
        candidates = ranked_choices(resolution.sources, state,
            preferred_audio_track_id=stable_audio_track_id,
            preferred_subtitle_track_id=stable_subtitle_track_id,
            require_healthy=require_healthy_source)
        providers = [
            {"provider_id": provider.provider_id, "label": provider.name}
            for provider in self.manager.list_providers(db)
            if provider.enabled and getattr(provider.capabilities, "movie" if identity.media_type == "movie" else "episode")
        ]
        source_session = None
        for source in candidates:
            candidate = delivery_broker.issue(profile_id, identity.content_key, source, audience)
            try:
                await set_session_choices(candidate, candidates, providers, state)
            except ClientCompatibilityError:
                source_sessions.discard(candidate.session_id)
                continue
            source_session = candidate
            break
        if source_session is None:
            excluded = set(excluded_provider_ids or ()) | {resolution.selected_provider_id}
            available = {p["provider_id"] for p in providers} - excluded
            if available:
                return await self.resolve(db, profile_id, identity, excluded_provider_ids=excluded,
                    audience=audience, prepare=prepare, inherited_preferences=inherited_preferences,
                    require_healthy_source=require_healthy_source,
                    preferred_audio_track_id=preferred_audio_track_id,
                    preferred_subtitle_track_id=preferred_subtitle_track_id)
            raise ClientCompatibilityError("no_compatible_source")
        if prepare:
            source_session.context["preparation"] = update.model_dump(mode="json")
        source_session.context["excluded_provider_ids"] = set(excluded_provider_ids or ())
        return self.session_view(
            state, source_session, resolution.attempts,
            stable_audio_track_id, stable_subtitle_track_id,
        )

    def session_view(self, state, source_session, attempts, audio_id=None, subtitle_id=None):
        source = source_session.source
        normalized_expires_at = (
            aware_utc(source.expires_at)
            if source.expires_at is not None
            else None
        )
        client_source = PlaybackClientSource(
            provider_id=source.provider_id,
            source_id=source.source_id,
            source_label=source.source_label,
            url=delivery_broker.client_url(source_session),
            protocol=source.protocol,
            quality=source.quality,
            audio_tracks=source.audio_tracks,
            subtitle_tracks=delivery_broker.client_subtitles(source_session),
            expires_at=normalized_expires_at,
        )
        caps = current_capabilities(source_session.context.get("capabilities"))
        if caps:
            client_source.subtitle_tracks = [t for t in client_source.subtitle_tracks if t.kind == "burned_in" or
                (caps.text_tracks and (caps.subtitle_formats is None or t.format is None or t.format.lower() in {f.lower() for f in caps.subtitle_formats}))]
        audio, subtitles = selections_for_source(
            client_source,
            preferred_audio_language=state.preferred_audio_language,
            preferred_audio_kind=state.preferred_audio_kind,
            preferred_audio_track_id=audio_id,
            subtitles_enabled=state.subtitles_enabled and (caps is None or caps.text_tracks),
            preferred_subtitle_language=state.preferred_subtitle_language,
            preferred_subtitle_track_id=subtitle_id,
        )
        refresh_at = source_refresh_at(source)
        session_refresh_at = source_session.retained_until - timedelta(minutes=2)
        refresh_at = min(refresh_at, session_refresh_at) if refresh_at else session_refresh_at

        ctx = request_client.get()
        if ctx and not source_session.context.get("preparation"):
            ctx["resolved"] = (source_session, {"content_key": state.content_key if hasattr(state, "content_key") else ContentIdentity(state.media_type, state.tmdb_id, state.season_number, state.episode_number).content_key,
                "media_type": state.media_type, "tmdb_id": state.tmdb_id, "season_number": state.season_number, "episode_number": state.episode_number})
            ctx["position"] = state.position_seconds
        return PlaybackSession(
            state=state_view(state),
            resolution=PlaybackResolutionSummary(
                selected_provider_id=(
                    source.provider_id
                ),
                attempts=attempts,
            ),
            selected_source=client_source,
            source_session_id=source_session.session_id,
            source_expires_at=normalized_expires_at,
            source_expiry_status=source_expiry_status(source),
            refresh_at=refresh_at,
            selected_audio=audio,
            selected_subtitles=subtitles,
            choices=quality_result(source_session.context.get("choices", PlaybackChoices()),
                state.preferred_quality_height, current_capabilities(source_session.context.get("capabilities")),
                source_session.context.get("incompatible_heights", ())),
            client_session_id=source_session.context.get("client_session_id"),
            preparation_only=bool(source_session.context.get("preparation")),
        )

    async def next_source(self, state, previous, audio_id=None, subtitle_id=None):
        # Consume the server-held candidate pool, never retry an already failed URL.
        sources = [s for s in previous.context.get("sources", []) if s.url != previous.source.url]
        ranked = ranked_choices(sources, state, capabilities=current_capabilities(previous.context.get("capabilities")))
        choices = previous.context.get("choices", PlaybackChoices())
        for candidate in ranked:
            replacement = delivery_broker.issue(state.profile_id, state.content_key, candidate, previous.audience)
            try:
                await set_session_choices(replacement, sources, choices.providers, state)
            except ClientCompatibilityError:
                source_sessions.discard(replacement.session_id)
                continue
            replacement.context["excluded_provider_ids"] = previous.context.get("excluded_provider_ids", set())
            # Track IDs are not portable between hosts; logical language/kind survive.
            return self.session_view(state, replacement, [])
        return None


playback_service = PlaybackService()
