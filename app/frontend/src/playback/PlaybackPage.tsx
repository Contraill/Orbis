import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  Link,
  useLocation,
  useParams,
} from "react-router-dom";

import {
  failoverPlayback,
  refreshPlayback,
  recoverPlayback,
  resolvePlayback,
  savePlaybackState,
} from "../api";
import MediaPlayer from "../player/MediaPlayer";
import type {
  AudioKind,
  AudioTrack,
  PlaybackIdentity,
  PlaybackFailure,
  PlaybackSession,
  PlaybackStateUpdate,
  SubtitleSelection,
  SubtitleTrack,
} from "../types";


const SAVE_INTERVAL_MS = 15_000;
const MAX_TIMER_MS = 2_147_000_000;


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
  const location = useLocation();
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
  const routeState = location.state as {
    title?: string;
    returnTo?: string;
  } | null;
  const returnTo = routeState?.returnTo ?? (
    mediaType === "movie"
      ? `/movie/${tmdbId}`
      : `/tv/${tmdbId}?season=${seasonNumber ?? 1}`
  );

  const [session, setSession] =
    useState<PlaybackSession | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [sourceStartPosition, setSourceStartPosition] =
    useState(0);
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
  const transitionRef = useRef(false);
  const saveInFlightRef = useRef<Promise<void> | null>(null);
  const completedRef = useRef(false);
  const latestRef = useRef({
    currentTime,
    duration,
    selectedAudio,
    preferredAudioLanguage,
    preferredAudioKind,
    subtitlesEnabled,
    subtitleLanguage,
    selectedSubtitle,
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
    selectedSubtitle,
    session,
  };

  const applySession = useCallback((
    next: PlaybackSession,
    resumePosition = next.state.resume_position_seconds,
  ) => {
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
    const boundedPosition = next.state.duration_seconds === null
      ? resumePosition
      : Math.min(resumePosition, next.state.duration_seconds);
    setCurrentTime(boundedPosition);
    setSourceStartPosition(boundedPosition);
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
    (completed?: boolean, keepalive = false): Promise<void> => {
      if (
        !identity ||
        !readyRef.current ||
        transitionRef.current
      ) {
        return Promise.resolve();
      }

      if (saveInFlightRef.current) {
        return saveInFlightRef.current;
      }

      const snapshot = stateSnapshot(completed);
      if (!snapshot) {
        return Promise.resolve();
      }

      const operation = (async () => {
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
      })();
      saveInFlightRef.current = operation;
      void operation.finally(() => {
        if (saveInFlightRef.current === operation) {
          saveInFlightRef.current = null;
        }
      });
      return operation;
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

  const requestReplacement = useCallback(
    async (
      mode: "failover" | "refresh" | "recover",
      reason?: string,
      failure?: PlaybackFailure,
    ) => {
      const latest = latestRef.current;
      if (
        !identity ||
        !latest.session ||
        transitionRef.current
      ) {
        return;
      }

      const snapshot = stateSnapshot();
      if (!snapshot) {
        return;
      }

      transitionRef.current = true;
      setFailoverBusy(true);
      setError(null);
      setMessage(
        mode === "refresh"
          ? "Refreshing expiring source…"
          : mode === "recover"
          ? "Recovering playback…"
          : reason
          ? `Source failed: ${reason}. Trying next provider…`
          : "Trying next provider…",
      );

      try {
        await saveInFlightRef.current;
        const trackPreferences = {
          preferred_audio_track_id:
            latest.selectedAudio?.track_id ?? null,
          preferred_subtitle_track_id:
            latest.selectedSubtitle?.track_id ?? null,
        };
        const next = mode === "recover" && failure
          ? await recoverPlayback(identity, {
            ...snapshot,
            ...trackPreferences,
            source_session_id: latest.session.source_session_id,
            failure,
          })
          : mode === "refresh"
          ? await refreshPlayback(identity, {
            ...snapshot,
            ...trackPreferences,
            source_session_id:
              latest.session.source_session_id,
          })
          : await failoverPlayback(identity, {
            ...snapshot,
            ...trackPreferences,
            failed_provider_id:
              latest.session.resolution.selected_provider_id,
          });
        applySession(
          next,
          latestRef.current.currentTime,
        );
        setMessage(
          mode === "refresh"
            ? "Playback source refreshed"
            : mode === "recover"
            ? "Playback recovered"
            : `Switched to ${next.resolution.selected_provider_id}`,
        );
      } catch (failoverError) {
        const errorMessage = failoverError instanceof Error
          ? failoverError.message
          : "No playback source is available";
        if (mode === "refresh") {
          setMessage(null);
          setError(
            `Source refresh failed: ${errorMessage}. ` +
            "The current source remains active.",
          );
        } else {
          setMessage(null);
          setError(
            reason
              ? `${errorMessage}. Initial source error: ${reason}`
              : errorMessage,
          );
        }
      } finally {
        transitionRef.current = false;
        setFailoverBusy(false);
      }
    },
    [identity, stateSnapshot, applySession],
  );

  useEffect(() => {
    const refreshAt = session?.refresh_at;
    if (!refreshAt) {
      return;
    }

    let timer: number | undefined;
    const schedule = () => {
      const remaining =
        Date.parse(refreshAt) - Date.now();
      if (!Number.isFinite(remaining)) {
        return;
      }
      if (remaining > MAX_TIMER_MS) {
        timer = window.setTimeout(schedule, MAX_TIMER_MS);
        return;
      }
      timer = window.setTimeout(() => {
        void requestReplacement("refresh");
      }, Math.max(0, remaining));
    };

    schedule();
    return () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [
    session?.source_session_id,
    session?.refresh_at,
    requestReplacement,
  ]);

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
          <Link className="back-link" to={returnTo}>
            ← Back to details
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
          <Link className="back-link" to={returnTo}>
            ← Back to details
          </Link>
          <p className="section-kicker">PLAYBACK</p>
          <h1>
            {routeState?.title ?? (
              identity.mediaType === "movie"
                ? `Movie ${identity.tmdbId}`
                : (
                  `TV ${identity.tmdbId} · ` +
                  `S${identity.seasonNumber}` +
                  `E${identity.episodeNumber}`
                )
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
          key={session.source_session_id}
          source={source}
          startPosition={sourceStartPosition}
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
          onError={(playerError, failure) => {
            void requestReplacement("recover", playerError, failure);
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
          onClick={() => void requestReplacement("failover")}
        >
          {failoverBusy ? "Switching…" : "Try next provider"}
        </button>
      </section>
    </main>
  );
}
