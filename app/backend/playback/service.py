from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.playback import (
    PlaybackState,
    playback_content_key,
)
from db.models.profile import Profile
from playback.matching import selections_for_source
from playback.delivery import delivery_broker
from playback.schemas import (
    MediaType,
    PlaybackClientSource,
    PlaybackResolutionSummary,
    PlaybackSession,
    PlaybackStateUpdate,
    PlaybackStateView,
)
from providers.manager import ProviderManager, provider_manager
from providers.source_policy import (
    aware_utc,
    select_source,
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


def upsert_playback_state(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    update: PlaybackStateUpdate,
) -> PlaybackState:
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
    ) -> PlaybackSession:
        state = get_playback_state(
            db,
            profile_id,
            identity,
        )
        preferred_provider_id = (
            state.last_provider_id
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
            update = PlaybackStateUpdate(
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
            )

        state = upsert_playback_state(
            db,
            profile_id,
            identity,
            update,
        )
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
        source = select_source(
            resolution.sources,
            preferred_audio_language=(
                state.preferred_audio_language
            ),
            preferred_audio_kind=state.preferred_audio_kind,
            preferred_audio_track_id=stable_audio_track_id,
            subtitles_enabled=state.subtitles_enabled,
            preferred_subtitle_language=(
                state.preferred_subtitle_language
            ),
            preferred_subtitle_track_id=stable_subtitle_track_id,
            require_healthy=require_healthy_source,
        )
        source_session = delivery_broker.issue(
            profile_id,
            identity.content_key,
            source,
            audience,
        )
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
            url=delivery_broker.client_url(source_session),
            protocol=source.protocol,
            quality=source.quality,
            audio_tracks=source.audio_tracks,
            subtitle_tracks=delivery_broker.client_subtitles(source_session),
            expires_at=normalized_expires_at,
        )
        audio, subtitles = selections_for_source(
            client_source,
            preferred_audio_language=state.preferred_audio_language,
            preferred_audio_kind=state.preferred_audio_kind,
            preferred_audio_track_id=audio_id,
            subtitles_enabled=state.subtitles_enabled,
            preferred_subtitle_language=state.preferred_subtitle_language,
            preferred_subtitle_track_id=subtitle_id,
        )
        refresh_at = source_refresh_at(source)
        session_refresh_at = source_session.retained_until - timedelta(minutes=2)
        refresh_at = min(refresh_at, session_refresh_at) if refresh_at else session_refresh_at

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
        )


playback_service = PlaybackService()
