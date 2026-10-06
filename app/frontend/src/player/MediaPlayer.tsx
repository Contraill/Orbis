import {
  useCallback,
  useEffect,
  useRef,
} from "react";

import type shaka from "shaka-player";

import type {
  AudioTrack,
  PlaybackSource,
  PlaybackFailure,
  SubtitleSelection,
} from "../types";
import { activeAudioLabel, audioMatches, chooseManifestAudio } from "./audioMatch";


type ShakaPlayer = shaka.Player;

interface MediaPlayerProps {
  videoElement?: (video: HTMLVideoElement | null) => void;
  source: PlaybackSource;
  startPosition: number;
  selectedAudio: AudioTrack | null;
  originalLanguage?: string | null;
  locale?: string;
  selectedSubtitles: SubtitleSelection;
  qualityHeight: number | null;
  qualityChoices?: { height: number; encoded_variants?: { width: number; height: number }[] }[];
  maxHeight?: number | null;
  autoPlay?: boolean;
  onPlay?: () => void;
  onProgress: (
    position: number,
    duration: number | null,
  ) => void;
  onPause: () => void;
  onEnded: () => void;
  onError: (message: string, failure: PlaybackFailure) => void;
  onAudioOutcome?: (outcome: { matched: boolean; activeLabel: string | null }) => void;
}


function normalizedLanguage(value: string | null) {
  return value?.replace(/_/g, "-").toLowerCase() ?? null;
}


function mimeType(source: PlaybackSource) {
  if (source.protocol === "hls") {
    return "application/x-mpegurl";
  }
  if (source.protocol === "dash") {
    return "application/dash+xml";
  }
  return undefined;
}


function textMimeType(format: string | null) {
  switch (format?.toLowerCase()) {
    case "vtt":
    case "webvtt":
      return "text/vtt";
    case "srt":
      return "application/x-subrip";
    case "ttml":
      return "application/ttml+xml";
    default:
      return undefined;
  }
}


function playbackFailure(error: unknown): PlaybackFailure {
  const value = (error ?? {}) as { category?: number; code?: number; data?: unknown[] };
  const data = value.data ?? [];
  const requestType = value.code === 1001 ? data[4]
    : value.code === 1002 ? data[2]
    : value.code === 1003 ? data[1] : undefined;
  return {
    category: value.category === 1 ? "network" : value.category === 3 ? "media" : "other",
    resource_type: requestType === 0 || requestType === 12 ? "manifest"
      : requestType === 1 ? "segment" : requestType === 6 ? "key" : "unknown",
    http_status: value.code === 1001 && typeof data[1] === "number" ? data[1] : null,
    code: typeof value.code === "number" ? value.code : null,
  };
}


function applySelections(
  player: ShakaPlayer,
  selectedAudio: AudioTrack | null,
  originalLanguage: string | null,
  selectedSubtitles: SubtitleSelection,
  qualityHeight: number | null,
  qualityChoices: { height: number; encoded_variants?: { width: number; height: number }[] }[],
  maxHeight: number | null = null,
) {
  const variants = player.getVariantTracks();
  const choice = qualityHeight === null ? undefined : qualityChoices.find(item => item.height === qualityHeight);
  const dimensions = choice?.encoded_variants ?? [];
  const inClass = (track: shaka.extern.Track) => dimensions.length
    ? dimensions.some(size => track.height === size.height && (track.width === size.width || track.width === null))
    : track.height === qualityHeight;
  const classVariants = choice ? variants.filter(inClass) : [];
  const heights = classVariants.map(track => track.height).filter((height): height is number => height !== null);
  const minimum = heights.length ? Math.min(...heights) : 0;
  const maximum = heights.length ? Math.min(Math.max(...heights), maxHeight ?? Infinity) : maxHeight ?? Infinity;
  // A consumer 1080p class may contain 1920x800 and 1920x1080 encodes.
  // Restrict Shaka by actual encoded dimensions, never by the class label.
  player.configure({ abr: { enabled: true, restrictions: {
    minHeight: minimum, maxHeight: maximum,
  } } });
  if (classVariants.length) {
    const active = variants.find(track => track.active);
    const candidate = [...classVariants].sort((a, b) => Number(b.language === active?.language) - Number(a.language === active?.language)
      || b.bandwidth - a.bandwidth || a.id - b.id)[0];
    if (candidate && active?.id !== candidate.id) player.selectVariantTrack(candidate, true);
  }
  if (selectedAudio) {
    const audio = chooseManifestAudio(classVariants.length ? classVariants : variants, selectedAudio, originalLanguage);
    if (audio && !audio.active) {
      const rendition = player.getAudioTracks().find(track =>
        track.label === audio.label && track.language === (audio.audioLanguage || audio.language));
      if (rendition) player.selectAudioTrack(rendition, 2);
      else player.selectVariantTrack(audio, true);
    }
  }

  const selectedTrack =
    selectedSubtitles.selected_track;
  const textTracks = player.getTextTracks();
  const textTrackId = Number(selectedTrack?.track_id);
  const textById = selectedTrack?.track_id !== null &&
    selectedTrack?.track_id !== undefined &&
    Number.isFinite(textTrackId)
    ? textTracks.find((track) => track.id === textTrackId)
    : undefined;
  const text = selectedTrack
    ? textById ?? textTracks.find((track) =>
        normalizedLanguage(track.language) ===
        normalizedLanguage(selectedTrack.language),
      )
    : null;

  player.selectTextTrack(text);
}


export default function MediaPlayer({
  videoElement,
  source,
  startPosition,
  selectedAudio,
  originalLanguage = null,
  locale = "en-US",
  selectedSubtitles,
  qualityHeight,
  qualityChoices = [],
  maxHeight = null,
  autoPlay = true,
  onPlay,
  onProgress,
  onPause,
  onEnded,
  onError,
  onAudioOutcome,
}: MediaPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoElementRef = useRef(videoElement);
  videoElementRef.current = videoElement;
  const attachVideo = useCallback((node: HTMLVideoElement | null) => {
    videoRef.current = node;
    videoElementRef.current?.(node);
  }, []);
  const playerRef = useRef<ShakaPlayer | null>(null);
  const audioRef = useRef({ selectedAudio, originalLanguage, locale, onAudioOutcome });
  audioRef.current = { selectedAudio, originalLanguage, locale, onAudioOutcome };
  const qualityChoicesRef = useRef(qualityChoices);
  qualityChoicesRef.current = qualityChoices;
  const reportAudio = (player: ShakaPlayer) => {
    const active = player.getVariantTracks().find(track => track.active);
    const selected = audioRef.current.selectedAudio;
    audioRef.current.onAudioOutcome?.({ matched: selected ? audioMatches(active, selected, audioRef.current.originalLanguage) : true, activeLabel: activeAudioLabel(active, audioRef.current.originalLanguage, audioRef.current.locale) });
  };
  const callbacksRef = useRef({
    onProgress,
    onPause,
    onPlay,
    onEnded,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = {
      onProgress,
      onPause,
      onPlay,
      onEnded,
      onError,
    };
  }, [onProgress, onPause, onPlay, onEnded, onError]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const tracks = video.textTracks;
    const observed = new Set<TextTrack>();
    const liftCues = () => {
      // Native and Shaka-created WebVTT cues otherwise sit underneath the
      // player timeline and its controls. Keep captions inside the video,
      // above the tallest mobile control bar, in normal and fullscreen mode.
      for (let index = 0; index < tracks.length; index++) {
        const cues = tracks[index].activeCues;
        if (!cues) continue;
        for (let cueIndex = 0; cueIndex < cues.length; cueIndex++) {
          const cue = cues[cueIndex];
          if (cue && "snapToLines" in cue && "line" in cue) {
            const vttCue = cue as VTTCue;
            if (vttCue.snapToLines || vttCue.line !== 68) {
              vttCue.snapToLines = false;
              vttCue.line = 68;
            }
          }
        }
      }
    };
    const attach = () => {
      for (let index = 0; index < tracks.length; index++) {
        const track = tracks[index];
        if (!observed.has(track)) {
          track.addEventListener("cuechange", liftCues);
          observed.add(track);
        }
      }
      liftCues();
    };
    tracks.addEventListener("addtrack", attach);
    video.addEventListener("timeupdate", liftCues);
    attach();
    return () => {
      tracks.removeEventListener("addtrack", attach);
      video.removeEventListener("timeupdate", liftCues);
      for (const track of observed) track.removeEventListener("cuechange", liftCues);
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    let cancelled = false;
    let errorReported = false;
    const initRequests = new Set<string>();

    const reportError = (error: unknown, terminal = true) => {
      if (cancelled || errorReported) return;
      if (!terminal && (error as { severity?: number })?.severity === 1) return;
      errorReported = true;
      const failure = playbackFailure(error);
      console.error("Playback engine failed", { category: failure.category, resource_type: failure.resource_type, code: failure.code });
      const failedUri = (error as { data?: unknown[] })?.data?.[0];
      if (typeof failedUri === "string" && initRequests.has(failedUri)) {
        failure.resource_type = "init";
      }
      callbacksRef.current.onError(
        "Playback could not continue",
        failure,
      );
    };

    if (source.protocol === "http") {
      const resume = () => {
        if (
          startPosition > 0 &&
          Number.isFinite(video.duration)
        ) {
          video.currentTime = Math.min(
            startPosition,
            video.duration,
          );
        }
      };

      video.addEventListener("loadedmetadata", resume);
      video.src = source.url;
      video.load();

      return () => {
        video.removeEventListener(
          "loadedmetadata",
          resume,
        );
        video.pause();
        video.removeAttribute("src");
        video.load();
      };
    }

    void (async () => {
      try {
        const { default: shakaPlayer } = await import(
          "shaka-player"
        );
        shakaPlayer.polyfill.installAll();

        if (
          !shakaPlayer.Player.isBrowserSupported()
        ) {
          throw new Error(
            "This browser does not support adaptive playback",
          );
        }
        if (cancelled) return;

        const player = new shakaPlayer.Player();
        playerRef.current = player;
        await player.attach(video);
        // Consumer quality is a class label; a 1080p-class cinema encode may
        // have only 800 physical lines. Apply its raw variant bounds after
        // the manifest loads, never pre-filter by the class number.
        player.configure({ restrictions: { maxHeight: maxHeight ?? Infinity }, abr: { restrictions: { minHeight: 0, maxHeight: maxHeight ?? Infinity } } });
        if (cancelled) return;
        player.getNetworkingEngine()?.registerRequestFilter((_type, request, context) => {
          if (context?.type === shakaPlayer.net.NetworkingEngine.AdvancedRequestType.INIT_SEGMENT) {
            for (const uri of request.uris) initRequests.add(uri);
          }
        });

        player.addEventListener("error", (event) => {
          reportError(
            (event as CustomEvent<unknown>).detail,
            false,
          );
        });
        player.addEventListener("variantchanged", () => reportAudio(player));
        player.addEventListener("adaptation", () => reportAudio(player));

        await player.load(
          source.url,
          startPosition,
          mimeType(source),
        );

        if (cancelled) {
          await player.destroy();
          return;
        }

        for (const track of source.subtitle_tracks) {
          if (track.kind !== "external" || !track.url) {
            continue;
          }

          await player.addTextTrackAsync(
            track.url,
            track.language ?? "und",
            "subtitles",
            textMimeType(track.format),
            undefined,
            track.label ?? undefined,
            track.forced,
          );
        }

        applySelections(
          player,
          selectedAudio,
          originalLanguage,
          selectedSubtitles,
          qualityHeight,
          qualityChoicesRef.current,
          maxHeight,
        );
        reportAudio(player);
      } catch (error) {
        reportError(error);
      }
    })();

    return () => {
      cancelled = true;
      const player = playerRef.current;
      playerRef.current = null;
      void player?.destroy();
    };
  }, [source, startPosition]);

  useEffect(() => {
    const player = playerRef.current;
    if (player) {
      applySelections(
        player,
        selectedAudio,
        originalLanguage,
        selectedSubtitles,
        qualityHeight,
        qualityChoices,
        maxHeight,
      );
      reportAudio(player);
    }
  }, [selectedAudio, originalLanguage, selectedSubtitles, qualityHeight, qualityChoices, maxHeight]);

  const externalTrack = source.protocol === "http"
    ? selectedSubtitles.selected_track
    : null;

  return (
    <video
      ref={attachVideo}
      className="media-player"
      autoPlay={autoPlay}
      playsInline
      onTimeUpdate={(event) => {
        const video = event.currentTarget;
        callbacksRef.current.onProgress(
          video.currentTime,
          Number.isFinite(video.duration)
            ? video.duration
            : null,
        );
      }}
      onPlay={() => callbacksRef.current.onPlay?.()}
      onPause={() => callbacksRef.current.onPause()}
      onEnded={() => callbacksRef.current.onEnded()}
      onError={() => {
        if (source.protocol === "http") {
          callbacksRef.current.onError(
            "Direct media playback failed",
            {
              category: videoRef.current?.error?.code === 2 ? "network" : "media",
              resource_type: "segment",
              http_status: null,
              code: videoRef.current?.error?.code ?? null,
            },
          );
        }
      }}
    >
      {externalTrack?.url && (
        <track
          key={externalTrack.url}
          src={externalTrack.url}
          srcLang={externalTrack.language ?? "und"}
          label={
            externalTrack.label ??
            externalTrack.language ??
            "Subtitles"
          }
          kind="subtitles"
          default={selectedSubtitles.enabled}
        />
      )}
    </video>
  );
}
