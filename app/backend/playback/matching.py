from playback.schemas import (
    AudioSelection,
    SubtitleSelection,
    normalize_language,
)
from providers.schemas import (
    AudioKind,
    AudioTrack,
    PlaybackSource,
    SubtitleTrack,
)


def _language(track: AudioTrack | SubtitleTrack) -> str | None:
    return normalize_language(track.language)


def _base_language(language: str | None) -> str | None:
    if language is None:
        return None
    return language.split("-", 1)[0]


def match_audio_track(
    tracks: list[AudioTrack],
    preferred_language: str | None,
    preferred_kind: AudioKind | None,
    preferred_track_id: str | None = None,
) -> AudioSelection:
    if not tracks:
        return AudioSelection(track=None, matched_by="none")

    language = normalize_language(preferred_language)
    base_language = _base_language(language)

    if preferred_track_id is not None:
        for track in tracks:
            if track.track_id == preferred_track_id:
                return AudioSelection(
                    track=track,
                    matched_by="track_id",
                )

    if language is not None and preferred_kind is not None:
        for track in tracks:
            if (
                _language(track) == language
                and track.kind == preferred_kind
            ):
                return AudioSelection(
                    track=track,
                    matched_by="language_and_kind",
                )

    if language is not None:
        for track in tracks:
            if _language(track) == language:
                return AudioSelection(
                    track=track,
                    matched_by="language",
                )

    if base_language is not None and preferred_kind is not None:
        for track in tracks:
            if (
                _base_language(_language(track)) == base_language
                and track.kind == preferred_kind
            ):
                return AudioSelection(
                    track=track,
                    matched_by="base_language_and_kind",
                )

    if preferred_kind is not None:
        for track in tracks:
            if track.kind == preferred_kind:
                return AudioSelection(
                    track=track,
                    matched_by="kind",
                )

    if base_language is not None:
        for track in tracks:
            if _base_language(_language(track)) == base_language:
                return AudioSelection(
                    track=track,
                    matched_by="base_language",
                )

    return AudioSelection(
        track=tracks[0],
        matched_by="provider_default",
    )


def _match_subtitle_language(
    tracks: list[SubtitleTrack],
    preferred_language: str | None,
    preferred_track_id: str | None = None,
) -> SubtitleTrack | None:
    if not tracks:
        return None

    language = normalize_language(preferred_language)

    if preferred_track_id is not None:
        for track in tracks:
            if track.track_id == preferred_track_id:
                return track

    if language is not None:
        for track in tracks:
            if _language(track) == language:
                return track

        base_language = _base_language(language)
        for track in tracks:
            if _base_language(_language(track)) == base_language:
                return track

    return tracks[0]


def match_subtitle_track(
    tracks: list[SubtitleTrack],
    enabled: bool,
    preferred_language: str | None,
    preferred_track_id: str | None = None,
) -> SubtitleSelection:
    burned_in = [
        track
        for track in tracks
        if track.kind == "burned_in"
    ]
    selectable = [
        track
        for track in tracks
        if track.kind != "burned_in"
    ]

    burned_in_track = _match_subtitle_language(
        burned_in,
        preferred_language,
    )
    selected_track = (
        _match_subtitle_language(
            selectable,
            preferred_language,
            preferred_track_id,
        )
        if enabled
        else None
    )

    return SubtitleSelection(
        enabled=(
            burned_in_track is not None
            or selected_track is not None
        ),
        can_disable=burned_in_track is None,
        selected_track=selected_track,
        burned_in_track=burned_in_track,
    )


def selections_for_source(
    source: PlaybackSource,
    *,
    preferred_audio_language: str | None,
    preferred_audio_kind: AudioKind | None,
    preferred_audio_track_id: str | None = None,
    subtitles_enabled: bool,
    preferred_subtitle_language: str | None,
    preferred_subtitle_track_id: str | None = None,
) -> tuple[AudioSelection, SubtitleSelection]:
    return (
        match_audio_track(
            source.audio_tracks,
            preferred_audio_language,
            preferred_audio_kind,
            preferred_audio_track_id,
        ),
        match_subtitle_track(
            source.subtitle_tracks,
            subtitles_enabled,
            preferred_subtitle_language,
            preferred_subtitle_track_id,
        ),
    )
