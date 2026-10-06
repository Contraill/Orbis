import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  useLocation,
  useParams,
  useNavigate,
} from "react-router-dom";

import {
  failoverPlayback,
  refreshPlayback,
  recoverPlayback,
  resolvePlayback,
  savePlaybackState,
  choosePlayback,
  ensureClientSession, heartbeatClient,
  getEpisodeLifecycle, prepareNextEpisode, transitionEpisode, request,
  getCatalogDetails,
  type EpisodeLifecycle, type ClientSessionView,
} from "../api";
import MediaPlayer from "../player/MediaPlayer";
import GlobalRoomControl from "../watch/GlobalRoomControl";
import { useGlobalWatchTogether } from "../watch/GlobalWatchTogether";
import PlayerOverlay from "./PlayerOverlay";
import OrbitalLoader from "./OrbitalLoader";
import "./player.css";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
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
  const { profile: activeProfile, reload: reloadProfile } = useProfile();
  const t = useText();
  const watch = useGlobalWatchTogether();
  const navigate = useNavigate();
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
    playbackSession?: PlaybackSession;
  } | null;
  const returnTo = routeState?.returnTo ?? (
    mediaType === "movie"
      ? `/movie/${tmdbId}`
      : `/tv/${tmdbId}?season=${seasonNumber ?? 1}`
  );

  const [session, setSession] =
    useState<PlaybackSession | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const pendingSeekRef = useRef<number | null>(null);
  const [sourceStartPosition, setSourceStartPosition] =
    useState(0);
  const [duration, setDuration] =
    useState<number | null>(null);
  const [selectedAudio, setSelectedAudio] =
    useState<AudioTrack | null>(null);
  const [audioOutcome, setAudioOutcome] = useState<{ matched: boolean; activeLabel: string | null } | null>(null);
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
  const [resolveRetry, setResolveRetry] = useState(0);
  const [failoverBusy, setFailoverBusy] = useState(false);
  const [message, setMessage] =
    useState<string | null>(null);
  const [error, setError] =
    useState<string | null>(null);

  const [lifecycle, setLifecycle] = useState<EpisodeLifecycle | null>(null);
  const roomActive = Boolean(watch.room);
  const [clientInfo, setClientInfo] = useState<ClientSessionView | null>(null);
  const [videoNode, setVideoNode] = useState<HTMLVideoElement | null>(null);
  const lastRoomSource = useRef<string | null>(null);
  useEffect(() => {
    if (!roomActive || !session?.source_session_id) { lastRoomSource.current = null; return; }
    if (lastRoomSource.current && lastRoomSource.current !== session.source_session_id) watch.send("preferences_changed");
    lastRoomSource.current = session.source_session_id;
  }, [roomActive, session?.source_session_id, watch.send]);
  const [nextCountdown, setNextCountdown] = useState<number | null>(null);
  const [catalogTitle, setCatalogTitle] = useState<string | null>(null);
  const [originalLanguage, setOriginalLanguage] = useState<string | null>(null);
  const preparedRef = useRef<string | undefined>(undefined);
  const preparingRef = useRef(false);
  const presenceState = useRef<"playing" | "paused">("paused");
  const readyRef = useRef(false);
  const transitionRef = useRef(false);
  const saveInFlightRef = useRef<Promise<void> | null>(null);
  const completedRef = useRef(false);
  const routeGeneration = useRef(0);
  const videoElement = useCallback((node: HTMLVideoElement | null) => setVideoNode(node), []);
  useEffect(() => {
    routeGeneration.current += 1;
    return () => { routeGeneration.current += 1; };
  }, [identity]);
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
    pendingSeekRef.current = null;
    setSourceStartPosition(boundedPosition);
    setDuration(next.state.duration_seconds);
    setSelectedAudio(audioTrack);
    setAudioOutcome(null);
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
        const client = await ensureClientSession(identity.profileId);
        if (cancelled) return;
        setClientInfo(client);
        const prepared = routeState?.playbackSession;
        const matches = prepared && prepared.state.profile_id === identity.profileId && prepared.state.tmdb_id === identity.tmdbId && prepared.state.season_number === (identity.seasonNumber ?? null) && prepared.state.episode_number === (identity.episodeNumber ?? null) && prepared.client_session_id === client.id;
        const shared = watch.room;
        const sameRoomContent = shared?.content?.media_type === identity.mediaType && shared.content.tmdb_id === identity.tmdbId &&
          shared.content.season_number === (identity.seasonNumber ?? null) && shared.content.episode_number === (identity.episodeNumber ?? null);
        const resolved = matches ? prepared : sameRoomContent ? (await request<{ playback: PlaybackSession }>(`/api/watch-together/rooms/${encodeURIComponent(shared.room_id)}/resolve`, {
          method: "POST", headers: { "X-Orbis-Session": client.id }, body: JSON.stringify({ content_revision: shared.content_revision }),
        })).playback : await resolvePlayback(identity);
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
  }, [identity, applySession, resolveRetry, watch.room?.content_revision, watch.room?.room_id]);

  useEffect(() => {
    if (!identity) return;
    let active = true;
    void getCatalogDetails(identity.mediaType, identity.tmdbId).then(value => {
      if (active) { setCatalogTitle(value.title); setOriginalLanguage(value.original_language ?? null); }
    }).catch(() => {});
    return () => { active = false; };
  }, [identity, routeState?.title, activeProfile?.locale]);

  useEffect(() => {
    let cancelled = false;
    setLifecycle(null); preparedRef.current = undefined; preparingRef.current = false;
    if (identity?.mediaType === "tv") {
      getEpisodeLifecycle(identity).then(value => { if (!cancelled) setLifecycle(value); })
        .catch(reason => { if (!cancelled) setMessage(String(reason)); });
    }
    return () => { cancelled = true; };
  }, [identity, activeProfile?.autoplay_next_episode]);

  useEffect(() => {
    if (!clientInfo || !session || !identity) return;
    const id = clientInfo.id;
    const sourceId = session.source_session_id;
    let cancelled = false;
    const beat = () => {
      if (completedRef.current || transitionRef.current) return;
      void heartbeatClient(id, presenceState.current, sourceId, latestRef.current.currentTime)
        .then(value => { if (!cancelled) setClientInfo(value); })
        .catch(reason => {
          if (!cancelled) { document.querySelector("video")?.pause(); setError(String(reason)); }
        });
    };
    const interval = window.setInterval(beat, 30_000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [clientInfo?.id, session?.source_session_id, identity]);

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
        preferred_provider_id: latest.session.state.preferred_provider_id ?? null,
        preferred_source_provider_id: latest.session.state.preferred_source_provider_id ?? null,
        preferred_source_id: latest.session.state.preferred_source_id ?? null,
        preferred_quality_height: latest.session.state.preferred_quality_height ?? null,
      };
    },
    [],
  );

  const persist = useCallback(
    (completed?: boolean, keepalive = false): Promise<void> => {
      if (
        !identity ||
        !readyRef.current ||
        transitionRef.current ||
        (completed === undefined && completedRef.current)
      ) {
        return Promise.resolve();
      }

      if (saveInFlightRef.current) {
        // Do not drop the final completion behind an ordinary periodic save.
        return completed === undefined ? saveInFlightRef.current
          : saveInFlightRef.current.then(() => persist(completed, keepalive));
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
    const stopPresence = () => {
      const current = latestRef.current.session;
      // Save durable progress before clearing transient presence. A stale source
      // stop is rejected by the server if an episode transition already won.
      void persist(undefined, true).then(() => {
        if (current?.client_session_id) return heartbeatClient(current.client_session_id, "stopped", current.source_session_id, 0, undefined, true);
      }).catch(() => {});
    };

    window.addEventListener("beforeunload", stopPresence);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener(
        "beforeunload",
        stopPresence,
      );
      stopPresence();
    };
  }, [persist]);

  const requestReplacement = useCallback(
    async (
      mode: "failover" | "refresh" | "recover",
      _reason?: string,
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
          ? "Refreshing playback…"
          : mode === "recover"
          ? "Recovering playback…"
          : "Finding another playable stream…",
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
            ? "Playback refreshed"
            : mode === "recover"
            ? "Playback recovered"
            : "Playback restored",
        );
      } catch {
        if (mode === "refresh") {
          setMessage(null);
          setError("Playback refresh failed. Please retry.");
        } else {
          setMessage(null);
          setError("Playback could not continue. Please retry.");
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

  async function changeChoice(preference: Partial<PlaybackStateUpdate>) {
    const latest = latestRef.current;
    const snapshot = stateSnapshot();
    if (!identity || !latest.session || !snapshot || transitionRef.current) return;
    transitionRef.current = true;
    setFailoverBusy(true);
    setError(null);
    try {
      await saveInFlightRef.current;
      const next = await choosePlayback(identity, {
        ...snapshot, ...preference,
        source_session_id: latest.session.source_session_id,
        preferred_audio_track_id: latest.selectedAudio?.track_id ?? null,
        preferred_subtitle_track_id: latest.selectedSubtitle?.track_id ?? null,
      });
      if (next.source_session_id === latest.session.source_session_id) {
        // Quality-only changes do not reload the manifest or reset delivery recovery.
        setSession({ ...next, selected_source: latest.session.selected_source });
      } else {
        applySession(next, latestRef.current.currentTime);
      }
      setMessage("Playback preferences updated. Unavailable preferences fall back automatically.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Choice could not be applied");
    } finally {
      transitionRef.current = false;
      setFailoverBusy(false);
    }
  }

  async function moveEpisode(direction: "next" | "previous") {
    if (!identity || transitionRef.current) return;
    const generation = routeGeneration.current;
    if (!completedRef.current) await persist();
    if (generation !== routeGeneration.current) return;
    transitionRef.current = true; setFailoverBusy(true); setError(null);
    try {
      if (roomActive) {
        const nextRef = direction === "next" ? lifecycle?.next : lifecycle?.previous;
        if (!nextRef?.aired) return;
        readyRef.current = false;
        await watch.start({ media_type: "tv", tmdb_id: identity.tmdbId, season_number: nextRef.season_number, episode_number: nextRef.episode_number }, `/watch/${identity.profileId}/tv/${identity.tmdbId}/season/${nextRef.season_number}/episode/${nextRef.episode_number}`, { returnTo });
        return;
      }
      const next = await transitionEpisode(identity, direction, direction === "next" ? preparedRef.current : undefined);
      if (generation !== routeGeneration.current) return;
      readyRef.current = false;
      navigate(`/watch/${identity.profileId}/tv/${next.state.tmdb_id}/season/${next.state.season_number}/episode/${next.state.episode_number}`, { state: { playbackSession: next, returnTo } });
    } catch (reason) { if (generation === routeGeneration.current) setError(String(reason)); }
    finally { transitionRef.current = false; setFailoverBusy(false); }
  }

  useEffect(() => {
    if (nextCountdown === null) return;
    if (nextCountdown <= 0) { setNextCountdown(null); void moveEpisode("next"); return; }
    const timer = window.setTimeout(() => setNextCountdown(value => value === null ? null : value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [nextCountdown]);

  useEffect(() => {
    if (!identity || identity.mediaType !== "tv" || !lifecycle?.autoplay_allowed || !duration || currentTime < duration - 75 || preparedRef.current || preparingRef.current || completedRef.current || roomActive) return;
    preparingRef.current = true;
    const generation = routeGeneration.current;
    void prepareNextEpisode(identity).then(prepared => { if (generation === routeGeneration.current) preparedRef.current = prepared.source_session_id; }).catch(() => {}).finally(() => { preparingRef.current = false; });
  }, [identity, lifecycle?.autoplay_allowed, duration, currentTime, roomActive]);

  const back = () => navigate(returnTo);
  if (loading) return <OrbitalLoader />;
  if (!identity || !session) return <main className="orbis-player-state" role="alert"><img src="/brand/standalone-icon.png" alt="" /><h1>{t("Playback is unavailable")}</h1><p>{t("Try again or choose another title.")}</p>{identity ? <button onClick={() => setResolveRetry(value => value + 1)}>{t("Try again")}</button> : null}<button onClick={back}>{t("Back to details")}</button></main>;

  const source = session.selected_source;
  const subtitleSelectionValue = subtitleSelection;
  const updateAutoplay = async (enabled: boolean) => {
    try {
      await request(`/api/profiles/${identity.profileId}`, { method: "PATCH", body: JSON.stringify({ autoplay_next_episode: enabled }) });
      await reloadProfile();
      setLifecycle(await getEpisodeLifecycle(identity));
    } catch { setError(t("Could not update autoplay preference.")); }
  };
  const chooseEpisode = async (season: number, episode: number) => {
    if (transitionRef.current) return;
    if (season === identity.seasonNumber && episode === identity.episodeNumber) return;
    await persist();
    readyRef.current = false;
    if (roomActive) {
      await watch.start({ media_type: "tv", tmdb_id: identity.tmdbId, season_number: season, episode_number: episode }, `/watch/${identity.profileId}/tv/${identity.tmdbId}/season/${season}/episode/${episode}`, { title: routeState?.title?.split(" · ")[0], returnTo });
      return;
    }
    navigate(`/watch/${identity.profileId}/tv/${identity.tmdbId}/season/${season}/episode/${episode}`, { state: { title: routeState?.title?.split(" · ")[0], returnTo } });
  };

  return <div className="orbis-player-route">
    <PlayerOverlay video={videoNode} identity={identity} title={routeState?.title?.split(" · ")[0] ?? catalogTitle ?? (identity.mediaType === "movie" ? t("Movie") : t("Series"))}
      session={session} currentTime={currentTime} duration={duration} busy={failoverBusy}
      lifecycle={lifecycle} selectedAudio={selectedAudio} audioOutcome={audioOutcome} selectedSubtitle={selectedSubtitle} subtitlesEnabled={subtitleSelectionValue.enabled}
      onBack={back}
      onSeekIntent={position => { pendingSeekRef.current = position; latestRef.current.currentTime = position; setCurrentTime(position); }}
      onSeekComplete={() => { pendingSeekRef.current = null; }}
      onQuality={height => void changeChoice({ preferred_quality_height: height })}
      onAudio={track => { setAudioOutcome(null); setSelectedAudio(track); setAudioLanguage(track.language); setAudioKind(track.kind); }}
      onSubtitle={track => { setSubtitlesEnabled(Boolean(track)); setSelectedSubtitle(track); setSubtitleLanguage(track?.language ?? null); }}
      onEpisode={(season, episode) => void chooseEpisode(season, episode)}
      onPrevious={() => void moveEpisode("previous")} onNext={() => void moveEpisode("next")}
      onAutoplay={enabled => void updateAutoplay(enabled)}
      alerts={<>
        {nextCountdown !== null ? <div className="orbis-player-next-prompt" role="status"><span>{t("Next episode")} · {nextCountdown}</span><button onClick={() => { setNextCountdown(null); void moveEpisode("next"); }}>{t("Play now")}</button><button onClick={() => setNextCountdown(null)}>{t("Cancel")}</button></div> : null}
        {error ? <div className="orbis-player-notice" role="alert"><span>{t("Playback could not continue. Please retry.")}</span><button onClick={() => void requestReplacement("recover", undefined, { category: "other", resource_type: "unknown", http_status: null, code: null })}>{t("Try again")}</button><button onClick={() => setError(null)} aria-label={t("Dismiss")}>×</button></div> : null}
        {message && !error && failoverBusy ? <div className="orbis-player-notice" role="status">{t("Restoring playback…")}</div> : null}
      </>}
      watchPanel={<GlobalRoomControl embedded currentContent={{ media_type: identity.mediaType, tmdb_id: identity.tmdbId, season_number: identity.seasonNumber ?? null, episode_number: identity.episodeNumber ?? null }} />}>
      <section className="playback-stage" aria-label={t("Video")}>
        <MediaPlayer key={session.source_session_id} videoElement={videoElement} source={source} startPosition={sourceStartPosition}
          selectedAudio={selectedAudio} originalLanguage={originalLanguage} locale={activeProfile?.locale} selectedSubtitles={subtitleSelectionValue}
          qualityHeight={session.choices.selected_quality_height} qualityChoices={session.choices.qualities} maxHeight={session.choices.max_compatible_height}
          onAudioOutcome={setAudioOutcome}
          autoPlay={!roomActive}
          onPlay={() => {
            presenceState.current = "playing";
            if (roomActive && watch.room?.state !== "playing") watch.send("play", { position: latestRef.current.currentTime });
            if (session.client_session_id) void heartbeatClient(session.client_session_id, "playing", session.source_session_id, latestRef.current.currentTime).then(setClientInfo).catch(() => setError(t("Playback session could not be updated.")));
          }}
          onProgress={(position, nextDuration) => {
            if (pendingSeekRef.current !== null && Math.abs(position - pendingSeekRef.current) > 1) return;
            latestRef.current.currentTime = position;
            setCurrentTime(Math.floor(position)); setDuration(nextDuration);
            if (position >= 5 && (nextDuration === null || nextDuration - position > 10)) completedRef.current = false;
          }}
          onPause={() => {
            presenceState.current = "paused"; void persist();
            if (roomActive && watch.room?.state !== "paused") watch.send("pause", { position: latestRef.current.currentTime });
            if (session.client_session_id && !completedRef.current && !transitionRef.current) void heartbeatClient(session.client_session_id, "paused", session.source_session_id, latestRef.current.currentTime).then(setClientInfo).catch(() => {});
          }}
          onEnded={() => {
            const generation = routeGeneration.current;
            completedRef.current = true;
            void (async () => {
              await persist(true);
              if (generation !== routeGeneration.current || identity.mediaType !== "tv" || activeProfile?.id !== identity.profileId) return;
              try { const navigation = await getEpisodeLifecycle(identity); if (navigation.autoplay_allowed && navigation.next?.aired && generation === routeGeneration.current) setNextCountdown(8); }
              catch { /* Completion remains valid when next metadata is absent. */ }
            })();
          }}
          onError={(playerError, failure) => { void requestReplacement("recover", playerError, failure); }} />
      </section>
    </PlayerOverlay>
  </div>;
}
