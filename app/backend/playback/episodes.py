"""Catalog-grounded episode navigation; absent metadata never means series finished."""
from datetime import date
from sqlalchemy import select
from fastapi import HTTPException
from db.models.catalog import CatalogEpisode, CatalogSeason
from db.models.foundation import LocalizedMetadata
from db.models.client_session import ContentMarkers
from db.models.profile import Profile
from metadata.catalog import cached
from metadata.localization import store_response
from metadata.tmdb import TMDBClient, TMDBError
from playback.schemas import EpisodeMarkers, PlaybackPreferences, PlaybackStateUpdate
from playback.service import get_playback_state, episode_identity, playback_service, upsert_playback_state
from playback.source_sessions import source_sessions, SourceSessionNotFound, SourceSessionScopeError
from playback.capabilities import request_client, current_capabilities
from providers.source_policy import source_expiry_status


def preferences(state):
    names = [*PlaybackPreferences.model_fields, "preferred_audio_language", "preferred_audio_kind", "subtitles_enabled", "preferred_subtitle_language"]
    return {name: getattr(state, name) for name in names} if state else {}


async def enrich_catalog(db, identity, locale):
    client = TMDBClient(locale)
    key = f"tv:{identity.tmdb_id}"
    try:
        if not cached(db, key, locale, True):
            store_response(db, locale, await client.tv_details(identity.tmdb_id))
        seasons = list(db.scalars(select(CatalogSeason.season_number).where(CatalogSeason.series_key == key, CatalogSeason.season_number > 0).order_by(CatalogSeason.season_number)))
        current = identity.season_number
        needed = {current}
        if current in seasons:
            index = seasons.index(current)
            if identity.episode_number == 1 and index > 0:
                needed.add(seasons[index - 1])
            season = db.get(CatalogSeason, (key, current))
            if season and season.episode_count and identity.episode_number >= season.episode_count and index + 1 < len(seasons):
                needed.add(seasons[index + 1])
        for number in sorted(needed):
            if not cached(db, f"{key}:season:{number}", locale):
                store_response(db, locale, await client.season_details(identity.tmdb_id, number))
        return None
    except TMDBError as exc:
        return exc.detail


def lifecycle(db, profile_id, identity):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    key = f"tv:{identity.tmdb_id}"
    season_number, episode_number = identity.season_number, identity.episode_number
    season = db.get(CatalogSeason, (key, season_number))
    seasons = list(db.scalars(select(CatalogSeason).where(CatalogSeason.series_key == key, CatalogSeason.season_number > 0).order_by(CatalogSeason.season_number)))
    current = db.get(CatalogEpisode, (key, season_number, episode_number))
    def describe(s, e):
        row = db.get(CatalogEpisode, (key, s, e))
        if not row:
            return None
        metadata = db.get(LocalizedMetadata, (f"{key}:season:{s}", profile.locale)) or db.get(LocalizedMetadata, (f"{key}:season:{s}", "en-US"))
        localized = next((i for i in metadata.data.get("episodes", []) if i["episode_number"] == e), {}) if metadata else {}
        return {"media_type": "tv", "tmdb_id": identity.tmdb_id, "season_number": s, "episode_number": e,
            "episode_tmdb_id": row.tmdb_id, "title": localized.get("name"), "air_date": row.air_date,
            "aired": bool(row.air_date and row.air_date <= date.today().isoformat()),
            "content_key": episode_identity(identity.tmdb_id, s, e).content_key}
    previous = describe(season_number, episode_number - 1) if episode_number > 1 else None
    following = describe(season_number, episode_number + 1)
    prior = [s for s in seasons if s.season_number < season_number]
    later = [s for s in seasons if s.season_number > season_number]
    if episode_number == 1 and prior and prior[-1].episode_count:
        previous = describe(prior[-1].season_number, prior[-1].episode_count)
    season_final = bool(current and season and season.episode_count == episode_number)
    if season_final and later and season_number > 0:
        following = describe(later[0].season_number, 1)
    metadata = db.get(LocalizedMetadata, (key, profile.locale)) or db.get(LocalizedMetadata, (key, "en-US"))
    data = metadata.data if metadata else {}
    definitive_seasons = [s["season_number"] for s in data.get("seasons", []) if s["season_number"] > 0]
    final_season = bool(definitive_seasons and season_number == max(definitive_seasons) and data.get("status") in ("Ended", "Canceled"))
    final_episode = bool(final_season and season_final and not following and not later)
    next_status = "available" if following and following["aired"] else "unreleased" if following else "series_finished" if final_episode else "metadata_incomplete"
    state = get_playback_state(db, profile_id, identity)
    marker = db.get(ContentMarkers, identity.content_key)
    return {"current": describe(season_number, episode_number) or {"media_type": "tv", "tmdb_id": identity.tmdb_id, "season_number": season_number, "episode_number": episode_number, "content_key": identity.content_key},
        "previous": previous, "next": following, "next_status": next_status,
        "season_transition": bool(following and following["season_number"] != season_number),
        "is_season_final": season_final, "is_final_season": final_season, "is_final_episode": final_episode,
        "autoplay_next": profile.autoplay_next_episode, "autoplay_allowed": profile.autoplay_next_episode and next_status == "available",
        "resume_position_seconds": state.position_seconds if state and not state.completed else 0,
        "current_completed": bool(state and state.completed),
        "markers": EpisodeMarkers.model_validate(marker.markers if marker else {}).model_dump(),
        "marker_source": marker.source if marker else None}


async def transition(db, profile_id, identity, direction, audience, prepare=False, prepared_id=None):
    navigation = lifecycle(db, profile_id, identity)
    target = navigation[direction]
    if not target or not target["aired"]:
        raise HTTPException(409, {"code": "episode_not_available", "next_status": navigation["next_status"]})
    destination = episode_identity(target["tmdb_id"], target["season_number"], target["episode_number"])
    inherited = preferences(get_playback_state(db, profile_id, identity))
    if prepared_id and not prepare:
        try:
            prepared = source_sessions.get(prepared_id, profile_id=profile_id, content_key=destination.content_key)
            ctx = request_client.get()
            if (prepared.audience == audience and prepared.context.get("preparation")
                and prepared.context.get("client_session_id") == (ctx["id"] if ctx else None)
                and prepared.context.get("inherited_preferences") == inherited
                and prepared.context.get("capabilities") == current_capabilities()
                and source_expiry_status(prepared.source) == "healthy"):
                current = get_playback_state(db, profile_id, destination)
                update = PlaybackStateUpdate.model_validate(prepared.context["preparation"])
                if current:
                    update.position_seconds, update.duration_seconds, update.completed = current.position_seconds, current.duration_seconds, current.completed
                state = upsert_playback_state(db, profile_id, destination, update)
                prepared.context.pop("preparation")
                return playback_service.session_view(state, prepared, [])
        except (SourceSessionNotFound, SourceSessionScopeError):
            pass  # Expired preparations use normal provider/source fallback.
    result = await playback_service.resolve(db, profile_id, destination, audience=audience, prepare=prepare, inherited_preferences=inherited)
    if prepare:
        source_sessions.get(result.source_session_id).context["inherited_preferences"] = inherited
    return result
