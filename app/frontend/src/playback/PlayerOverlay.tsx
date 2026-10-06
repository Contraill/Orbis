import { useEffect, useRef, useState } from "react";
import { getCatalogDetails, getSeasonDetails, listPlaybackStates } from "../api";
import { useText } from "../app/i18n";
import type { EpisodeLifecycle } from "../api";
import type { AudioTrack, PlaybackIdentity, PlaybackSession, PlaybackState, SeasonDetails, SubtitleTrack } from "../types";
import OrbitalLoader from "./OrbitalLoader";

export type PlayerMenu = "quality" | "audio" | "subtitles" | "episodes" | "together" | null;
type Props = {
  children: React.ReactNode;
  alerts?: React.ReactNode;
  video: HTMLVideoElement | null; identity: PlaybackIdentity; title: string; session: PlaybackSession;
  currentTime: number; duration: number | null; busy: boolean;
  lifecycle: EpisodeLifecycle | null; selectedAudio: AudioTrack | null; selectedSubtitle: SubtitleTrack | null;
  audioOutcome?: { matched: boolean; activeLabel: string | null } | null;
  subtitlesEnabled: boolean;
  onQuality: (height: number | null) => void; onAudio: (track: AudioTrack) => void;
  onSubtitle: (track: SubtitleTrack | null) => void; onEpisode: (season: number, episode: number) => void;
  onPrevious: () => void; onNext: () => void; onAutoplay: (enabled: boolean) => void;
  onBack: () => void; watchPanel: React.ReactNode;
  onSeekIntent?: (position: number) => void;
  onSeekComplete?: () => void;
  onMenuChange?: (menu: PlayerMenu) => void;
};
const labelTrack = (track: AudioTrack | SubtitleTrack) => [track.label || track.language || "Default", track.kind === "burned_in" ? "burned in" : null].filter(Boolean).join(" · ");
const time = (seconds: number) => { const safe = Math.max(0, Math.floor(seconds)); return `${Math.floor(safe / 3600) ? `${Math.floor(safe / 3600)}:` : ""}${String(Math.floor(safe / 60) % 60).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`; };

export default function PlayerOverlay(props: Props) {
  const t = useText();
  const [menu, setMenu] = useState<PlayerMenu>(null);
  const [visible, setVisible] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [seeking, setSeeking] = useState(false);
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);
  const [buffering, setBuffering] = useState(false);
  const pendingSeekRef = useRef<number | null>(null);
  const seekCompleteRef = useRef(props.onSeekComplete);
  seekCompleteRef.current = props.onSeekComplete;
  const [fullscreen, setFullscreen] = useState(false);
  const [buffered, setBuffered] = useState(0);
  const [episodeSeason, setEpisodeSeason] = useState(props.identity.seasonNumber ?? 1);
  const [seasonNumbers, setSeasonNumbers] = useState<number[]>([]);
  const [season, setSeason] = useState<SeasonDetails | null>(null);
  const [episodeStates, setEpisodeStates] = useState<PlaybackState[]>([]);
  const hideTimer = useRef<number | null>(null);
  const keyboardFocus = useRef(false);
  const lastPointer = useRef<{ x: number; y: number } | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const shell = useRef<HTMLElement | null>(null);
  const menuRefValue = useRef<PlayerMenu>(null);
  menuRefValue.current = menu;
  const actionsRef = useRef({ onBack: props.onBack, onMenuChange: props.onMenuChange });
  actionsRef.current = { onBack: props.onBack, onMenuChange: props.onMenuChange };

  useEffect(() => {
    const back = (event: KeyboardEvent) => {
      if (event.key !== "Escape" && event.key !== "Backspace") return;
      if (event.key === "Backspace" && (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || (event.target instanceof HTMLElement && event.target.isContentEditable))) return;
      event.preventDefault();
      if (menuRefValue.current) {
        setMenu(null);
        actionsRef.current.onMenuChange?.(null);
        setVisible(true);
        window.setTimeout(() => trigger.current?.focus(), 0);
      } else if (document.fullscreenElement === shell.current) {
        void document.exitFullscreen();
      } else actionsRef.current.onBack();
    };
    window.addEventListener("keydown", back);
    return () => window.removeEventListener("keydown", back);
  }, []);

  useEffect(() => {
    const video = props.video;
    if (!video) return;
    const sync = () => {
      setPlaying(!video.paused && !video.ended);
      if (video.duration && video.buffered.length) setBuffered(video.buffered.end(video.buffered.length - 1) / video.duration * 100);
    };
    for (const event of ["play", "pause", "ended", "progress", "loadedmetadata"]) video.addEventListener(event, sync);
    sync();
    return () => { for (const event of ["play", "pause", "ended", "progress", "loadedmetadata"]) video.removeEventListener(event, sync); };
  }, [props.video]);

  useEffect(() => {
    const video = props.video;
    if (!video) return;
    const waiting = () => { if (!video.paused || pendingSeekRef.current !== null) setBuffering(true); };
    const ready = () => {
      if (video.readyState >= 3) setBuffering(false);
      const target = pendingSeekRef.current;
      if (target !== null && !video.seeking && video.readyState >= 3 && Math.abs(video.currentTime - target) <= 1) {
        pendingSeekRef.current = null;
        delete video.dataset.orbisPendingSeek;
        setPendingSeek(null);
        seekCompleteRef.current?.();
      }
    };
    for (const name of ["waiting", "stalled", "seeking"]) video.addEventListener(name, waiting);
    for (const name of ["seeked", "canplay", "playing"]) video.addEventListener(name, ready);
    ready();
    return () => {
      for (const name of ["waiting", "stalled", "seeking"]) video.removeEventListener(name, waiting);
      for (const name of ["seeked", "canplay", "playing"]) video.removeEventListener(name, ready);
      delete video.dataset.orbisPendingSeek;
    };
  }, [props.video]);

  const scheduleHide = () => {
    if (hideTimer.current) window.clearTimeout(hideTimer.current);
    if (playing && !menu && !seeking) hideTimer.current = window.setTimeout(() => {
      if (!keyboardFocus.current || !shell.current?.contains(document.activeElement) || document.activeElement === shell.current) setVisible(false);
    }, 3200);
  };
  useEffect(() => {
    if (!playing || menu || seeking) setVisible(true);
    scheduleHide();
    return () => { if (hideTimer.current) window.clearTimeout(hideTimer.current); };
  }, [playing, menu, seeking]);

  useEffect(() => {
    if (!menu) return;
    setVisible(true);
    const timer = window.setTimeout(() => menuRef.current?.querySelector<HTMLElement>("button:not(:disabled), select")?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [menu]);

  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement === shell.current);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);

  useEffect(() => {
    if (menu !== "episodes" || props.identity.mediaType !== "tv") return;
    let active = true;
    void Promise.all([getCatalogDetails("tv", props.identity.tmdbId), listPlaybackStates(props.identity.profileId)]).then(([details, states]) => {
      if (!active) return;
      const numbers = details.seasons.filter(item => item.season_number >= 0 && item.episode_count > 0).map(item => item.season_number);
      setSeasonNumbers(numbers.length ? numbers : [props.identity.seasonNumber ?? 1]);
      setEpisodeStates(states.filter(state => state.media_type === "tv" && state.tmdb_id === props.identity.tmdbId));
    }).catch(() => {});
    return () => { active = false; };
  }, [menu, props.identity.mediaType, props.identity.tmdbId, props.identity.profileId, props.identity.seasonNumber]);

  useEffect(() => {
    if (menu !== "episodes" || props.identity.mediaType !== "tv") return;
    let active = true;
    setSeason(null);
    void getSeasonDetails(props.identity.tmdbId, episodeSeason).then(value => { if (active) setSeason(value); }).catch(() => {});
    return () => { active = false; };
  }, [menu, episodeSeason, props.identity.mediaType, props.identity.tmdbId]);

  const open = (next: PlayerMenu, button: HTMLButtonElement) => {
    trigger.current = button;
    const value = menu === next ? null : next;
    setMenu(value); props.onMenuChange?.(value);
    if (!value) window.setTimeout(() => button.focus(), 0);
  };
  const close = () => { setMenu(null); props.onMenuChange?.(null); window.setTimeout(() => trigger.current?.focus(), 0); };
  const reveal = () => { setVisible(true); scheduleHide(); };
  const direction = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLTextAreaElement) return;
    const active = document.activeElement;
    if (!(active instanceof HTMLElement) || active === shell.current) return;
    const scope = menu ? menuRef.current : shell.current;
    const nodes = Array.from(scope?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)') ?? []).filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== "hidden");
    if (!nodes.includes(active)) return;
    const current = active.getBoundingClientRect(), cx = current.left + current.width / 2, cy = current.top + current.height / 2;
    const horizontal = event.key === "ArrowLeft" || event.key === "ArrowRight", sign = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
    const target = nodes.filter(node => node !== active).map(node => { const r = node.getBoundingClientRect(); const dx = r.left + r.width / 2 - cx, dy = r.top + r.height / 2 - cy; const primary = (horizontal ? dx : dy) * sign; return { node, primary, score: primary + Math.abs(horizontal ? dy : dx) * 2.4 }; }).filter(item => item.primary > 4).sort((a, b) => a.score - b.score)[0];
    if (target) { event.preventDefault(); target.node.focus(); target.node.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  };
  const canControl = true;
  const seek = (value: number) => {
    if (!props.video || !canControl || !Number.isFinite(value)) return;
    const target = Math.max(0, props.duration == null ? value : Math.min(value, props.duration));
    pendingSeekRef.current = target;
    props.video.dataset.orbisPendingSeek = String(target);
    setPendingSeek(target);
    setBuffering(true);
    props.onSeekIntent?.(target);
    props.video.currentTime = target;
  };
  const play = () => { if (!props.video || !canControl) return; if (props.video.paused) void props.video.play().catch(() => {}); else props.video.pause(); };
  const menuButton = (name: Exclude<PlayerMenu, null>, text: string, disabled = false) => <button type="button" className="orbis-player-action" disabled={disabled} aria-expanded={menu === name} aria-controls="orbis-player-menu" onClick={event => open(name, event.currentTarget)}>{text}</button>;
  const choice = (selected: boolean, name: string, action: () => void, disabled = false) => <button type="button" aria-pressed={selected} className={selected ? "selected" : ""} disabled={disabled || props.busy} onClick={() => { action(); close(); }}>{name}{selected ? <span aria-hidden="true">✓</span> : null}</button>;
  const source = props.session.selected_source;
  const displayedTime = pendingSeek ?? props.currentTime;
  const subtitles = source.subtitle_tracks.filter(track => track.kind !== "burned_in");
  const burned = props.session.selected_subtitles.burned_in_track;
  const markers = props.lifecycle?.markers;
  const marker = (start: string, end: string) => markers?.[start] != null && markers?.[end] != null && displayedTime >= markers[start]! && displayedTime < markers[end]! ? markers[end] : null;
  const skipIntro = marker("intro_start", "intro_end");
  const skipRecap = marker("recap_start", "recap_end");
  const nextAtCredits = markers?.credits_start != null && displayedTime >= markers.credits_start && props.lifecycle?.next?.aired;

  return <main ref={shell} className={`orbis-player${visible || menu ? " controls-visible" : " controls-hidden"}`} onMouseMove={event => {
    const previous = lastPointer.current;
    if (previous && Math.abs(event.clientX - previous.x) + Math.abs(event.clientY - previous.y) < 2) return;
    lastPointer.current = { x: event.clientX, y: event.clientY };
    keyboardFocus.current = false; reveal();
  }} onPointerDown={() => { keyboardFocus.current = false; reveal(); }} onTouchStart={reveal} onKeyDown={event => {
    keyboardFocus.current = true;
    reveal();
    if (event.target === shell.current && event.key === "Enter") play();
    if (event.key === " " && event.target === shell.current) { event.preventDefault(); play(); }
    if (event.target === shell.current && event.key === "ArrowLeft") { event.preventDefault(); seek(displayedTime - 10); }
    if (event.target === shell.current && event.key === "ArrowRight") { event.preventDefault(); seek(displayedTime + 10); }
    direction(event);
  }} tabIndex={0} aria-label={t("Video player")}>
    <div className="orbis-player-video">{props.children}</div>
    {buffering || pendingSeek !== null || props.busy ? <OrbitalLoader embedded /> : null}
    <button className="orbis-player-reveal" type="button" aria-label={t(visible ? "Play or pause" : "Show controls")} onClick={() => { if (!visible) reveal(); else play(); }} />
    <div className="orbis-player-top orbis-player-glass"><button type="button" className="orbis-player-back" onClick={props.onBack} aria-label={t("Back to details")}>←</button><div><strong>{props.title}</strong>{props.identity.mediaType === "tv" ? <small>S{String(props.identity.seasonNumber).padStart(2, "0")} E{String(props.identity.episodeNumber).padStart(2, "0")}</small> : null}</div></div>
    {props.busy ? <div className="orbis-player-status" role="status">{t("Restoring playback…")}</div> : null}
    {skipIntro != null && canControl ? <button className="orbis-player-skip" onClick={() => seek(skipIntro)}>{t("Skip Intro")}</button> : skipRecap != null && canControl ? <button className="orbis-player-skip" onClick={() => seek(skipRecap)}>{t("Skip Recap")}</button> : null}
    {nextAtCredits && canControl ? <button className="orbis-player-next" onClick={props.onNext}>{t("Next episode")} →</button> : null}
    <div className="orbis-player-center"><button type="button" onClick={() => seek(displayedTime - 10)} disabled={!canControl} aria-label={t("Back 10 seconds")}>↶<small>10</small></button><button className="main" type="button" onClick={play} disabled={!canControl} aria-label={t(playing ? "Pause" : "Play")}>{playing ? "Ⅱ" : "▶"}</button><button type="button" onClick={() => seek(displayedTime + 10)} disabled={!canControl} aria-label={t("Forward 10 seconds")}>↷<small>10</small></button></div>
    <div className="orbis-player-bottom orbis-player-glass">
      <div className="orbis-player-time"><span>{time(displayedTime)}</span><div className="orbis-player-track"><div className="orbis-player-buffered" style={{ width: `${Math.min(100, buffered)}%` }} /></div><input type="range" min={0} max={Math.max(1, props.duration ?? 1)} step={0.1} value={Math.min(displayedTime, props.duration ?? 1)} disabled={!props.duration || !canControl} aria-label={t("Seek position")} onPointerDown={() => setSeeking(true)} onPointerUp={() => setSeeking(false)} onBlur={() => setSeeking(false)} onChange={event => seek(Number(event.target.value))} /><span>{props.duration == null ? "--:--" : time(props.duration)}</span></div>
      <nav className="orbis-player-actions" aria-label={t("Playback options")}>{props.identity.mediaType === "tv" ? menuButton("episodes", t("Episodes")) : null}{menuButton("quality", t("Quality"))}{menuButton("audio", t("Audio"))}{menuButton("subtitles", t("Subtitles"))}{menuButton("together", t("Watch Together"))}<button type="button" className="orbis-player-action" aria-label={t(fullscreen ? "Exit fullscreen" : "Fullscreen")} onClick={() => { if (document.fullscreenElement === shell.current) void document.exitFullscreen(); else void shell.current?.requestFullscreen(); }}>{fullscreen ? "⤡" : "⤢"}</button></nav>
    </div>
    <div id="orbis-player-menu" ref={menuRef} className={`orbis-player-menu orbis-player-glass${menu === "episodes" || menu === "together" ? " wide" : ""}`} hidden={!menu} role="dialog" aria-label={t(menu === "together" ? "Watch Together" : menu === "episodes" ? "Episodes" : "Playback options") }><header><h2>{t(menu === "quality" ? "Quality" : menu === "audio" ? "Audio" : menu === "subtitles" ? "Subtitles" : menu === "episodes" ? "Episodes" : "Watch Together")}</h2><button type="button" onClick={close} aria-label={t("Close menu")}>×</button></header>
      {menu === "quality" ? <div className="orbis-player-options">{choice(!props.session.state.preferred_quality_height, t("Auto"), () => props.onQuality(null))}{props.session.choices.qualities.map(item => <div key={item.height}>{choice(props.session.state.preferred_quality_height === item.height, item.label, () => props.onQuality(item.height))}</div>)}{["unavailable_fallback", "incompatible_fallback"].includes(props.session.choices.quality_outcome ?? "") ? <p>{t("Requested quality is unavailable on this device or source. Orbis chose a compatible option.")}</p> : null}<p>{t("Now playing")} · {props.session.choices.selected_quality_height ? `${props.session.choices.selected_quality_height}p` : t("Auto")}</p></div> : null}
      {menu === "audio" ? <div className="orbis-player-options">{source.audio_tracks.length ? source.audio_tracks.map((item, index) => <div key={item.track_id ?? index}>{choice(props.audioOutcome?.matched === true && props.selectedAudio?.track_id === item.track_id, labelTrack(item), () => props.onAudio(item))}</div>) : <p>{t("Provider default")}</p>}{props.audioOutcome?.activeLabel ? <p>{t("Now playing")} · {props.audioOutcome.activeLabel}</p> : null}{props.audioOutcome?.matched === false && props.audioOutcome.activeLabel ? <p>{t("Requested audio is unavailable; playing the available track.")}</p> : null}</div> : null}
      {menu === "subtitles" ? <div className="orbis-player-options">{burned ? <p>{t("Burned-in subtitles cannot be turned off.")}</p> : choice(!props.subtitlesEnabled, t("Off"), () => props.onSubtitle(null))}{subtitles.map((item, index) => <div key={item.track_id ?? index}>{choice(props.subtitlesEnabled && props.selectedSubtitle?.track_id === item.track_id, labelTrack(item), () => props.onSubtitle(item))}</div>)}</div> : null}
      {menu === "episodes" ? <div className="orbis-player-episodes"><div className="orbis-player-episode-nav"><button onClick={props.onPrevious} disabled={!props.lifecycle?.previous?.aired || props.busy || !canControl}>← {t("Previous episode")}</button><button onClick={props.onNext} disabled={!props.lifecycle?.next?.aired || props.busy || !canControl}>{t("Next episode")} →</button></div><label>{t("Season")}<select value={episodeSeason} onChange={event => setEpisodeSeason(Number(event.target.value))}>{seasonNumbers.map(number => <option value={number} key={number}>{t("Season")} {number}</option>)}</select></label><label className="orbis-player-toggle"><input type="checkbox" checked={props.lifecycle?.autoplay_next ?? false} onChange={event => props.onAutoplay(event.target.checked)} />{t("Autoplay next episode")}</label><div className="orbis-player-episode-list">{season?.episodes.map(episode => { const state = episodeStates.find(item => item.season_number === episodeSeason && item.episode_number === episode.episode_number); const current = episodeSeason === props.identity.seasonNumber && episode.episode_number === props.identity.episodeNumber; return <button className={current ? "current" : ""} key={episode.episode_number} disabled={props.busy || !canControl} onClick={() => props.onEpisode(episodeSeason, episode.episode_number)}>{episode.still_url ? <img src={episode.still_url} loading="lazy" alt="" /> : <span className="orbis-player-episode-placeholder">{episode.episode_number}</span>}<span><small>S{String(episodeSeason).padStart(2, "0")} E{String(episode.episode_number).padStart(2, "0")}{current ? ` · ${t("Now playing")}` : ""}</small><strong>{episode.name || t("Untitled episode")}</strong>{state?.completed ? <small>{t("Completed")}</small> : state && state.resume_position_seconds > 0 ? <small>{time(state.resume_position_seconds)} {t("watched")}</small> : null}</span></button>; })}{!season ? <p>{t("Loading…")}</p> : null}</div></div> : null}
      <div id="global-watch-player-slot" hidden={menu !== "together"}>{props.watchPanel}</div>
    </div>
    {props.alerts}
  </main>;
}
