import {
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


type ShakaPlayer = shaka.Player;

const SHAKA_ERROR_CATEGORIES: Record<number, string> = {
  1: "network",
  2: "text",
  3: "media",
  4: "manifest",
  5: "streaming",
  6: "DRM",
  7: "player",
  8: "cast",
  9: "storage",
  10: "ads",
};

const SHAKA_ERROR_SEVERITIES: Record<number, string> = {
  1: "recoverable",
  2: "critical",
};

interface MediaPlayerProps {
  source: PlaybackSource;
  startPosition: number;
  selectedAudio: AudioTrack | null;
  selectedSubtitles: SubtitleSelection;
  qualityHeight: number | null;
  maxHeight?: number | null;
  onPlay?: () => void;
  onProgress: (
    position: number,
    duration: number | null,
  ) => void;
  onPause: () => void;
  onEnded: () => void;
  onError: (message: string, failure: PlaybackFailure) => void;
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


function diagnosticValue(value: unknown): string {
  if (typeof value === "string") {
    try {
      const url = new URL(value);
      if (url.protocol === "http:" || url.protocol === "https:") {
        return `${url.origin}${url.pathname}`;
      }
    } catch {
      // The diagnostic value is not a URL.
    }
    return value.length > 160
      ? `${value.slice(0, 157)}…`
      : value;
  }
  if (
    value === null ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  if (value === undefined) return "undefined";
  if (Array.isArray(value)) {
    return `[${value.slice(0, 4).map(diagnosticValue).join(", ")}]`;
  }
  return Object.prototype.toString.call(value);
}


function playbackErrorMessage(error: unknown) {
  if (error && typeof error === "object") {
    const candidate = error as {
      severity?: unknown;
      category?: unknown;
      code?: unknown;
      data?: unknown;
      message?: unknown;
    };
    if (typeof candidate.code === "number") {
      const category = typeof candidate.category === "number"
        ? SHAKA_ERROR_CATEGORIES[candidate.category] ??
          `category ${candidate.category}`
        : "unknown-category";
      const severity = typeof candidate.severity === "number"
        ? SHAKA_ERROR_SEVERITIES[candidate.severity] ??
          `severity ${candidate.severity}`
        : "unknown-severity";
      const data = Array.isArray(candidate.data)
        ? candidate.data.slice(0, 5).map(
          (value, index) => `${index}=${diagnosticValue(value)}`,
        )
        : [];
      return (
        `Shaka ${category} error ${candidate.code} ` +
        `(${severity}${data.length ? `; ${data.join(", ")}` : ""})`
      );
    }
    if (typeof candidate.message === "string") {
      return candidate.message;
    }
  }
  return error instanceof Error
    ? error.message
    : "Playback source failed";
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
  selectedSubtitles: SubtitleSelection,
  qualityHeight: number | null,
  maxHeight: number | null = null,
) {
  // Restrict ABR by logical height, not a volatile Shaka variant ID.
  // Keep the master URL and networking/recovery hooks intact.
  const available = player.getVariantTracks().some(track => track.height === qualityHeight);
  const height = available ? qualityHeight : null;
  player.configure({ abr: { enabled: true, restrictions: {
    minHeight: height ?? 0, maxHeight: height ?? maxHeight ?? Infinity,
  } } });
  if (height !== null) {
    const variants = player.getVariantTracks();
    const active = variants.find(track => track.active);
    const candidate = variants.find(track => track.height === height && track.language === active?.language)
      ?? variants.find(track => track.height === height);
    if (candidate && active?.height !== height) player.selectVariantTrack(candidate, true);
  }
  if (selectedAudio) {
    const variants = player.getVariantTracks().filter(track => height === null || track.height === height);
    const trackId = Number(selectedAudio.track_id);
    const audioById = selectedAudio.track_id !== null &&
      Number.isFinite(trackId)
      ? variants.find((track) => track.id === trackId)
      : undefined;
    const audio = audioById ?? variants.find((track) =>
      normalizedLanguage(track.language) ===
      normalizedLanguage(selectedAudio.language),
    );

    if (audio) {
      player.selectVariantTrack(audio, true);
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
  source,
  startPosition,
  selectedAudio,
  selectedSubtitles,
  qualityHeight,
  maxHeight = null,
  onPlay,
  onProgress,
  onPause,
  onEnded,
  onError,
}: MediaPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<ShakaPlayer | null>(null);
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
      console.error(playbackErrorMessage(error), error);
      const failure = playbackFailure(error);
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
        player.configure({ restrictions: { maxHeight: maxHeight ?? Infinity }, abr: { restrictions: { minHeight: qualityHeight ?? 0, maxHeight: qualityHeight ?? maxHeight ?? Infinity } } });
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
          selectedSubtitles,
          qualityHeight,
          maxHeight,
        );
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
        selectedSubtitles,
        qualityHeight,
        maxHeight,
      );
    }
  }, [selectedAudio, selectedSubtitles, qualityHeight, maxHeight]);

  const externalTrack = source.protocol === "http"
    ? selectedSubtitles.selected_track
    : null;

  return (
    <video
      ref={videoRef}
      className="media-player"
      controls
      autoPlay
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
