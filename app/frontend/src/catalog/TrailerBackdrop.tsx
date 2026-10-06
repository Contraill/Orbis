import { useEffect, useMemo, useRef, useState } from "react";
import type { CatalogDetails } from "../types";
import { useText } from "../app/i18n";

type YouTubePlayer = { mute: () => void; unMute: () => void; playVideo: () => void; destroy: () => void };
type YouTubeApi = { Player: new (node: HTMLElement, options: Record<string, unknown>) => YouTubePlayer };
declare global { interface Window { YT?: YouTubeApi; onYouTubeIframeAPIReady?: () => void } }
let apiPromise: Promise<YouTubeApi> | null = null;
function youtubeApi(): Promise<YouTubeApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!apiPromise) apiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { previous?.(); if (window.YT?.Player) resolve(window.YT); else reject(new Error("YouTube player unavailable")); };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => { apiPromise = null; reject(new Error("YouTube player unavailable")); };
    document.head.append(script);
  });
  return apiPromise;
}

export default function TrailerBackdrop({ videos, initiallyMuted, onPlayingChange }: { videos: CatalogDetails["videos"]; initiallyMuted: boolean; onPlayingChange?: (playing: boolean) => void }) {
  const t = useText();
  const mount = useRef<HTMLDivElement>(null);
  const player = useRef<YouTubePlayer | null>(null);
  const [candidate, setCandidate] = useState(0);
  const [muted, setMuted] = useState(true);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { onPlayingChange?.(playing); }, [playing, onPlayingChange]);
  const choices = useMemo(() => videos.filter(video => (video.type === "Trailer" || video.type === "Teaser") && video.site === "YouTube" && /^[\w-]{6,32}$/.test(video.key)).sort((a, b) => Number(b.type === "Trailer") - Number(a.type === "Trailer") || Number(b.official) - Number(a.official)), [videos]);
  const trailer = choices[candidate];
  useEffect(() => {
    if (!trailer || !mount.current) return;
    let cancelled = false;
    let played = false;
    let retriedMuted = false;
    let triedSound = false;
    setPlaying(false); setMuted(true);
    const timeout = window.setTimeout(() => { if (!played && !cancelled) setCandidate(index => Math.min(index + 1, choices.length)); }, 12000);
    void youtubeApi().then(YT => {
      if (cancelled || !mount.current) return;
      const node = document.createElement("div");
      mount.current.replaceChildren(node);
      player.current = new YT.Player(node, {
        videoId: trailer.key,
        host: "https://www.youtube-nocookie.com",
        playerVars: { autoplay: 1, mute: 1, controls: 0, playsinline: 1, rel: 0, origin: window.location.origin },
        events: {
          onReady: ({ target }: { target: YouTubePlayer }) => {
            const iframe = mount.current?.querySelector("iframe");
            iframe?.setAttribute("tabindex", "-1");
            iframe?.setAttribute("aria-hidden", "true");
            target.mute(); target.playVideo();
          },
          onStateChange: ({ data, target }: { data: number; target: YouTubePlayer }) => {
            if (data === 1) { played = true; setPlaying(true); if (!initiallyMuted && !triedSound) { triedSound = true; target.unMute(); setMuted(false); } }
            else if (data === 0 || data === 2) setPlaying(false);
          },
          onAutoplayBlocked: ({ target }: { target: YouTubePlayer }) => { setMuted(true); setPlaying(false); if (!retriedMuted) { retriedMuted = true; target.mute(); target.playVideo(); } },
          onError: () => { setPlaying(false); setCandidate(index => Math.min(index + 1, choices.length)); },
        },
      });
    }).catch(() => { if (!cancelled) setCandidate(index => Math.min(index + 1, choices.length)); });
    return () => { cancelled = true; window.clearTimeout(timeout); player.current?.destroy(); player.current = null; mount.current?.replaceChildren(); };
  }, [trailer?.key, initiallyMuted, choices.length]);
  if (!trailer) return null;
  function sound() { if (!player.current) return; if (muted) player.current.unMute(); else player.current.mute(); setMuted(!muted); }
  return <div className={`trailer-layer ${playing ? "is-playing" : ""}`} aria-label={trailer.name || t("Trailer")}>
    <div ref={mount} className="trailer-mount" />
    {playing ? <button className="trailer-sound" onClick={sound} aria-pressed={!muted} aria-label={t(muted ? "Trailer sound on" : "Trailer sound off")}>{muted ? "♪̸" : "♪"}</button> : null}
  </div>;
}
