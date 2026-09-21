import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  Link,
  useParams,
} from "react-router-dom";

import {
  failoverPlayback,
  getPlaybackState,
  resolvePlayback,
  savePlaybackState,
} from "../api";
import MediaPlayer from "../player/MediaPlayer";
import type {
  AudioKind,
  AudioTrack,
  PlaybackIdentity,
  PlaybackSession,
  PlaybackStateUpdate,
  SubtitleSelection,
  SubtitleTrack,
} from "../types";


const SAVE_INTERVAL_MS = 15_000;


function parsePositive(value: string | undefined) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0
    ? parsed
    : null;
}


function parseSeason(value: string | undefined) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0
    ? parsed
    : null;
}


function formatTime(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remaining = String(safe % 60).padStart(2, "0");
  return `${minutes}:${remaining}`;
}


function sameAudioTrack(
  left: AudioTrack,
  right: AudioTrack | null,
) {
  if (!right) return false;
  if (left.track_id && right.track_id) {
    return left.track_id === right.track_id;
  }
  return (
    left.language === right.language &&
    left.kind === right.kind &&
    left.label === right.label
  );
}


function sameSubtitleTrack(
  left: SubtitleTrack,
  right: SubtitleTrack | null,
) {
  if (!right) return false;
  if (left.track_id && right.track_id) {
    return left.track_id === right.track_id;
  }
  return (
    left.language === right.language &&
    left.kind === right.kind &&
    left.label === right.label
  );
}


export default function PlaybackPage() {
  const {
    profileId,
    mediaType,
    tmdbId,
    seasonNumber,
    episodeNumber,
  } = useParams();

  const identity = useMemo<PlaybackIdentity | null>(() => {
    const profile = parsePositive(profileId);
    const tmdb = parsePositive(tmdbId);

    if (!profile || !tmdb) {
      return null;
    }

    if (mediaType === "movie") {
      return {
        profileId: profile,
        mediaType: "movie",
        tmdbId: tmdb,
      };
    }

    const season = parseSeason(seasonNumber);
    const episode = parsePositive(episodeNumber);
    if (mediaType !== "tv" || season === null || !episode) {
      return null;
    }

    return {
      profileId: profile,
      mediaType: "tv",
      tmdbId: tmdb,
      seasonNumber: season,
      episodeNumber: episode,
    };
  }, [
    profileId,
    mediaType,
    tmdbId,
    seasonNumber,
    episodeNumber,
  ]);

  const [session, setSession] =
    useState<PlaybackSession | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] =
    useState<number | null>(null);
  const [selectedAudio, setSelectedAudio] =
    useState<AudioTrack | null>(null);
  const [preferredAudioLanguage, setAudioLanguage] =
    useState<string | null>(null);
  const [preferredAudioKind, setAudioKind] =
    useState<AudioKind | null>(null);
  const [subtitlesEnabled, setSubtitlesEnabled] =
    useState(false);
  const [subtitleLanguage, setSubtitleLanguage] =
    useState<string | null>(null);
  const [selectedSubtitle, setSelectedSubtitle] =
    useState<SubtitleTrack | null>(null);
  const [loading, setLoading] = useState(true);
  const [failoverBusy, setFailoverBusy] = useState(false);
  const [message, setMessage] =
    useState<string | null>(null);
  const [error, setError] =
    useState<string | null>(null);

  const readyRef = useRef(false);
  const failoverRef = useRef(false);
  const completedRef = useRef(false);
  const latestRef = useRef({
    currentTime,
    duration,
    selectedAudio,
    preferredAudioLanguage,
    preferredAudioKind,
    subtitlesEnabled,
    subtitleLanguage,
    session,
  });

  latestRef.current = {
    currentTime,
    duration,
    selectedAudio,
    preferredAudioLanguage,
    preferredAudioKind,
    subtitlesEnabled,
    subtitleLanguage,
    session,
  };

  const applySession = useCallback((next: PlaybackSession) => {
    const source = next.selected_source;
    const audioTrack = source.audio_tracks.find(
      (track) => sameAudioTrack(
        track,
        next.selected_audio.track,
      ),
    ) ?? source.audio_tracks[0] ?? null;
    const subtitleTrack = source.subtitle_tracks.find(
      (track) => sameSubtitleTrack(
        track,
        next.selected_subtitles.selected_track,
      ),
    ) ?? null;

    setSession(next);
    setCurrentTime(next.state.resume_position_seconds);
    setDuration(next.state.duration_seconds);
    setSelectedAudio(audioTrack);
    setAudioLanguage(
      next.state.preferred_audio_language,
    );
    setAudioKind(next.state.preferred_audio_kind);
    setSubtitlesEnabled(next.state.subtitles_enabled);
    setSubtitleLanguage(
      next.state.preferred_subtitle_language,
    );
    setSelectedSubtitle(subtitleTrack);
    completedRef.current = next.state.completed;
    readyRef.current = true;
  }, []);

  useEffect(() => {
    if (!identity) {
      setLoading(false);
      setError("Invalid playback route");
      return;
    }

    let cancelled = false;
    readyRef.current = false;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const saved = await getPlaybackState(identity);
        if (cancelled) {
          return;
        }

        if (saved) {
          setCurrentTime(saved.resume_position_seconds);
          setDuration(saved.duration_seconds);
          setAudioLanguage(
            saved.preferred_audio_language,
          );
          setAudioKind(saved.preferred_audio_kind);
          setSubtitlesEnabled(saved.subtitles_enabled);
          setSubtitleLanguage(
            saved.preferred_subtitle_language,
          );
        }

        const resolved = await resolvePlayback(identity);
        if (!cancelled) {
          applySession(resolved);
        }
      } catch (reason) {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Playback could not be resolved",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [identity, applySession]);

  const stateSnapshot = useCallback(
    (completed?: boolean): PlaybackStateUpdate | null => {
      const latest = latestRef.current;
      if (!latest.session) {
        return null;
      }

      return {
        position_seconds: latest.currentTime,
        duration_seconds: latest.duration,
        completed: completed ?? completedRef.current,
        last_provider_id:
          latest.session.resolution.selected_provider_id,
        preferred_audio_language:
          latest.preferredAudioLanguage,
        preferred_audio_kind:
          latest.preferredAudioKind,
        subtitles_enabled: latest.subtitlesEnabled,
        preferred_subtitle_language:
          latest.subtitleLanguage,
      };
    },
    [],
  );

  const persist = useCallback(
    async (completed?: boolean, keepalive = false) => {
      if (!identity || !readyRef.current) {
        return;
      }

      const snapshot = stateSnapshot(completed);
      if (!snapshot) {
        return;
      }

      try {
        await savePlaybackState(
          identity,
          snapshot,
          keepalive,
        );
      } catch (reason) {
        if (!keepalive) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Playback progress could not be saved",
          );
        }
      }
    },
    [identity, stateSnapshot],
  );

  useEffect(() => {
    const interval = window.setInterval(() => {
      void persist();
    }, SAVE_INTERVAL_MS);
    const beforeUnload = () => {
      void persist(undefined, true);
    };

    window.addEventListener("beforeunload", beforeUnload);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener(
        "beforeunload",
        beforeUnload,
      );
      void persist(undefined, true);
    };
  }, [persist]);

  const requestFailover = useCallback(
    async (reason?: string) => {
      const latest = latestRef.current;
      if (
        !identity ||
        !latest.session ||
        failoverRef.current
      ) {
        return;
      }

      const snapshot = stateSnapshot();
      if (!snapshot) {
        return;
      }

      failoverRef.current = true;
      setFailoverBusy(true);
      setError(null);
      setMessage(
        reason
          ? `Source failed: ${reason}. Trying next provider…`
          : "Trying next provider…",
      );

      try {
        const next = await failoverPlayback(
          identity,
          {
            ...snapshot,
            failed_provider_id:
              latest.session.resolution.selected_provider_id,
          },
        );
        applySession(next);
        setMessage(
          `Switched to ${next.resolution.selected_provider_id}`,
        );
      } catch (failoverError) {
        setError(
          failoverError instanceof Error
            ? failoverError.message
            : "No fallback provider is available",
        );
      } finally {
        failoverRef.current = false;
        setFailoverBusy(false);
      }
    },
    [identity, stateSnapshot, applySession],
  );

  const subtitleSelection = useMemo<SubtitleSelection>(() => {
    const burned = session?.selected_subtitles
      .burned_in_track ?? null;

    return {
      enabled: burned !== null || subtitlesEnabled,
      can_disable: burned === null,
      selected_track: subtitlesEnabled
        ? selectedSubtitle
        : null,
      burned_in_track: burned,
    };
  }, [session, subtitlesEnabled, selectedSubtitle]);

  if (loading) {
    return (
      <main className="playback-page playback-centered">
        Resolving playback…
      </main>
    );
  }

  if (!identity || !session) {
    return (
      <main className="playback-page playback-centered">
        <div>
          <p className="banner error-banner">
            {error ?? "Playback is unavailable"}
          </p>
          <Link className="back-link" to="/">
            ← Home
          </Link>
        </div>
      </main>
    );
  }

  const source = session.selected_source;
  const selectableSubtitles = source.subtitle_tracks.filter(
    (track) => track.kind !== "burned_in",
  );

  return (
    <main className="playback-page">
      <header className="playback-header">
        <div>
          <Link className="back-link" to="/">
            ← Home
          </Link>
          <p className="section-kicker">PLAYBACK</p>
          <h1>
            {identity.mediaType === "movie"
              ? `Movie ${identity.tmdbId}`
              : (
                `TV ${identity.tmdbId} · ` +
                `S${identity.seasonNumber}` +
                `E${identity.episodeNumber}`
              )}
          </h1>
        </div>

        <div className="playback-provider">
          <span>Provider</span>
          <strong>
            {session.resolution.selected_provider_id}
          </strong>
          <small>
            {source.protocol.toUpperCase()}
            {source.quality ? ` · ${source.quality}` : ""}
          </small>
        </div>
      </header>

      {error && (
        <div className="banner error-banner">{error}</div>
      )}
      {message && (
        <div className="banner success-banner">
          {message}
        </div>
      )}

      <section className="playback-stage">
        <MediaPlayer
          key={`${source.provider_id}:${source.url}`}
          source={source}
          startPosition={session.state.resume_position_seconds}
          selectedAudio={selectedAudio}
          selectedSubtitles={subtitleSelection}
          onProgress={(position, nextDuration) => {
            setCurrentTime(position);
            setDuration(nextDuration);
            if (
              position >= 5 &&
              (
                nextDuration === null ||
                nextDuration - position > 10
              )
            ) {
              completedRef.current = false;
            }
          }}
          onPause={() => void persist()}
          onEnded={() => {
            completedRef.current = true;
            void persist(true);
          }}
          onError={(playerError) => {
            void requestFailover(playerError);
          }}
        />
      </section>

      <section className="playback-controls panel">
        <div>
          <span className="control-label">Position</span>
          <strong>
            {formatTime(currentTime)}
            {duration !== null
              ? ` / ${formatTime(duration)}`
              : ""}
          </strong>
        </div>

        <label>
          <span className="control-label">Audio</span>
          <select
            value={
              selectedAudio
                ? source.audio_tracks.findIndex(
                  (track) => sameAudioTrack(
                    track,
                    selectedAudio,
                  ),
                )
                : -1
            }
            disabled={source.audio_tracks.length === 0}
            onChange={(event) => {
              const track = source.audio_tracks[
                Number(event.target.value)
              ] ?? null;
              setSelectedAudio(track);
              setAudioLanguage(track?.language ?? null);
              setAudioKind(track?.kind ?? null);
            }}
          >
            {source.audio_tracks.length === 0 && (
              <option value={-1}>Provider default</option>
            )}
            {source.audio_tracks.map((track, index) => (
              <option
                key={track.track_id ?? `${track.language}-${index}`}
                value={index}
              >
                {track.label ?? track.language ?? "Unknown"}
                {` · ${track.kind}`}
              </option>
            ))}
          </select>
        </label>

        <label className="subtitle-toggle">
          <input
            type="checkbox"
            checked={subtitleSelection.enabled}
            disabled={!subtitleSelection.can_disable}
            onChange={(event) => {
              setSubtitlesEnabled(event.target.checked);
              if (
                event.target.checked &&
                !selectedSubtitle
              ) {
                const first = selectableSubtitles[0] ?? null;
                setSelectedSubtitle(first);
                setSubtitleLanguage(
                  first?.language ?? null,
                );
              }
            }}
          />
          <span>
            {subtitleSelection.can_disable
              ? "Subtitles"
              : "Burned-in subtitles"}
          </span>
        </label>

        <label>
          <span className="control-label">
            Subtitle language
          </span>
          <select
            value={
              selectedSubtitle
                ? selectableSubtitles.findIndex(
                  (track) => sameSubtitleTrack(
                    track,
                    selectedSubtitle,
                  ),
                )
                : -1
            }
            disabled={
              !subtitlesEnabled ||
              selectableSubtitles.length === 0
            }
            onChange={(event) => {
              const track = selectableSubtitles[
                Number(event.target.value)
              ] ?? null;
              setSelectedSubtitle(track);
              setSubtitleLanguage(track?.language ?? null);
            }}
          >
            {selectableSubtitles.length === 0 && (
              <option value={-1}>Unavailable</option>
            )}
            {selectableSubtitles.map((track, index) => (
              <option
                key={track.track_id ?? `${track.language}-${index}`}
                value={index}
              >
                {track.label ?? track.language ?? "Unknown"}
                {` · ${track.kind}`}
              </option>
            ))}
          </select>
        </label>

        <button
          className="button secondary"
          disabled={failoverBusy}
          onClick={() => void requestFailover()}
        >
          {failoverBusy ? "Switching…" : "Try next provider"}
        </button>
      </section>
    </main>
  );
}
