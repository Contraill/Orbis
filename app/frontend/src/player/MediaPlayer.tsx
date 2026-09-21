import {
  useEffect,
  useRef,
} from "react";

import type shaka from "shaka-player";

import type {
  AudioTrack,
  PlaybackSource,
  SubtitleSelection,
} from "../types";


type ShakaPlayer = shaka.Player;

interface MediaPlayerProps {
  source: PlaybackSource;
  startPosition: number;
  selectedAudio: AudioTrack | null;
  selectedSubtitles: SubtitleSelection;
  onProgress: (
    position: number,
    duration: number | null,
  ) => void;
  onPause: () => void;
  onEnded: () => void;
  onError: (message: string) => void;
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


function applySelections(
  player: ShakaPlayer,
  selectedAudio: AudioTrack | null,
  selectedSubtitles: SubtitleSelection,
) {
  if (selectedAudio) {
    const variants = player.getVariantTracks();
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
    onEnded,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = {
      onProgress,
      onPause,
      onEnded,
      onError,
    };
  }, [onProgress, onPause, onEnded, onError]);

  useEffect(() => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    let cancelled = false;

    const reportError = (error: unknown) => {
      const message = error instanceof Error
        ? error.message
        : "Playback source failed";
      callbacksRef.current.onError(message);
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
          cancelled ||
          !shakaPlayer.Player.isBrowserSupported()
        ) {
          throw new Error(
            "This browser does not support adaptive playback",
          );
        }

        const player = new shakaPlayer.Player(video);
        playerRef.current = player;

        player.addEventListener("error", (event) => {
          reportError(
            (event as CustomEvent<unknown>).detail,
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
        );
      } catch (error) {
        if (!cancelled) {
          reportError(error);
        }
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
      );
    }
  }, [selectedAudio, selectedSubtitles]);

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
      onPause={() => callbacksRef.current.onPause()}
      onEnded={() => callbacksRef.current.onEnded()}
      onError={() => {
        if (source.protocol === "http") {
          callbacksRef.current.onError(
            "Direct media playback failed",
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
