import { useEffect, useRef, useState } from "react";
import { request } from "../api";
import type { PlaybackIdentity, PlaybackSession } from "../types";

type Content = { media_type: "movie" | "tv"; tmdb_id: number; season_number: number | null; episode_number: number | null };
type Room = { type: "state"; room_id: string; revision: number; content_revision: number; content: Content; content_key: string; host_id: string; status: string; state: string; position: number; rate: number; participants: { id: string; profile_id: number; name: string; connected: boolean; ready: boolean }[]; participant_id?: string };
type Props = { identity: PlaybackIdentity; clientId: string; sourceId: string; onResolved: (playback: PlaybackSession) => void; onActive: (active: boolean) => void; beforeTransition: () => Promise<void> };

export default function WatchTogetherPanel(props: Props) {
  const storageKey = `orbis.watch-room.${props.clientId}`;
  const [roomId, setRoomId] = useState(() => sessionStorage.getItem(storageKey) ?? "");
  const [code, setCode] = useState("");
  const [room, setRoom] = useState<Room | null>(null);
  const [status, setStatus] = useState("Not connected");
  const [error, setError] = useState("");
  const [debug, setDebug] = useState("");
  const [retry, setRetry] = useState(0);
  const latest = useRef(props); latest.current = props;
  const current = useRef<Room | null>(null);
  const participant = useRef("");
  const socket = useRef<WebSocket | null>(null);
  const appliedContent = useRef(0);
  const resolving = useRef(false);
  const mutedUntil = useRef(0);
  const resetRateAt = useRef(0);
  const currentSource = useRef(props.sourceId);
  const alignedSource = useRef("");
  const rateSupported = useRef(true);

  function send(type: string, fields: Record<string, unknown> = {}) {
    if (socket.current?.readyState === WebSocket.OPEN && current.current) {
      socket.current.send(JSON.stringify({ type, revision: current.current.revision, ...fields }));
    }
  }
  function detach() {
    socket.current?.close(); sessionStorage.removeItem(storageKey);
    current.current = null; appliedContent.current = 0; setRoomId(""); setRoom(null);
    latest.current.onActive(false);
    const video = document.querySelector<HTMLVideoElement>(".playback-stage video");
    if (video) video.playbackRate = 1;
  }
  async function enter(create: boolean) {
    try {
      setError("");
      const i = latest.current.identity;
      const path = create ? "/api/watch-together/rooms" : `/api/watch-together/rooms/${encodeURIComponent(code.trim())}/join`;
      const value = await request<Room>(path, { method: "POST", headers: { "X-Orbis-Session": props.clientId }, ...(create ? { body: JSON.stringify({ content: { media_type: i.mediaType, tmdb_id: i.tmdbId, season_number: i.seasonNumber ?? null, episode_number: i.episodeNumber ?? null }, position: document.querySelector<HTMLVideoElement>(".playback-stage video")?.currentTime ?? 0 }) } : {}) });
      participant.current = value.participant_id ?? "";
      sessionStorage.setItem(storageKey, value.room_id); setRoomId(value.room_id);
    } catch (reason) { setError(String(reason)); }
  }

  useEffect(() => {
    if (!roomId) return;
    let cancelled = false;
    let retryTimer: number | undefined;
    let ws: WebSocket;
    latest.current.onActive(true);
    appliedContent.current = 0; current.current = null;
    const video = () => document.querySelector<HTMLVideoElement>(".playback-stage video");
    const enforce = (state: string, position: number, action: string, rate = 1, duration = 0) => {
      const v = video();
      if (!v || v.readyState < 1 || resolving.current) return;
      // No-op heartbeat replies must not suppress a real native user action.
      // Only media changes initiated by synchronization need echo suppression.
      const changesPlayback = action === "seek" || (state === "paused" && !v.paused)
        || (state !== "paused" && v.paused && !v.ended);
      if (changesPlayback) mutedUntil.current = performance.now() + 750;
      if (action === "seek") v.currentTime = Math.max(0, Number.isFinite(v.duration) ? Math.min(position, v.duration) : position);
      try { v.playbackRate = rate; } catch { rateSupported.current = false; }
      resetRateAt.current = duration ? performance.now() + duration * 1000 : 0;
      if (state === "paused") v.pause();
      else if (v.paused && !v.ended) void v.play().catch(() => setError("Browser blocked autoplay; press Play to join the room timeline."));
    };
    async function prepare(state: Room) {
      if (resolving.current || cancelled) return;
      resolving.current = true;
      try {
        await latest.current.beforeTransition();
        if (cancelled) return;
        const result = await request<{ playback: PlaybackSession; room: Room }>(`/api/watch-together/rooms/${roomId}/resolve`, { method: "POST", headers: { "X-Orbis-Session": latest.current.clientId }, body: JSON.stringify({ content_revision: state.content_revision }) });
        if (cancelled || current.current?.content_revision !== state.content_revision) return;
        appliedContent.current = state.content_revision;
        mutedUntil.current = performance.now() + 1000;
        // Start at the canonical room position, never another profile's resume.
        result.playback.state.resume_position_seconds = result.room.position;
        latest.current.onResolved(result.playback);
        currentSource.current = result.playback.source_session_id;
      } catch (reason) { if (!cancelled) setError(`Own source resolution failed: ${String(reason)}`); }
      finally { resolving.current = false; }
    }
    function connect() {
      if (cancelled) return;
      setStatus("Connecting");
      ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/watch-together/rooms/${roomId}/ws`);
      socket.current = ws;
      ws.onopen = () => { setStatus("Connected"); ws.send(JSON.stringify({ session_id: latest.current.clientId })); };
      ws.onmessage = event => {
        const value = JSON.parse(event.data);
        if (value.type === "welcome") { participant.current = value.participant_id; return; }
        if (value.type === "replaced") { cancelled = true; ws.close(); setStatus("Connection replaced"); return; }
        if (value.type === "error") { setError(value.code); return; }
        if (value.type === "state") {
          const state = value as Room;
          if (current.current && state.revision < current.current.revision) return;
          const old = current.current;
          current.current = state; setRoom(state);
          if (state.status !== "open" || !state.participants.some(p => p.id === participant.current)) { cancelled = true; detach(); setStatus("Room closed / left"); return; }
          if (appliedContent.current !== state.content_revision) {
            mutedUntil.current = performance.now() + 750;
            video()?.pause();
            void prepare(state); return;
          }
          if (!old || old.state !== state.state || Math.abs(state.position-(video()?.currentTime ?? state.position)) >= 2) {
            enforce(state.state,state.position, "seek");
          } else enforce(state.state,state.position,"none");
        } else if (value.type === "sync" && value.revision === current.current?.revision && appliedContent.current === value.content_revision) {
          enforce(value.state,value.position,value.action,value.rate,value.duration);
          setDebug(`${value.action}; drift ${value.drift.toFixed(2)}s; rate ${value.rate.toFixed(2)}`);
        }
      };
      ws.onclose = event => {
        if (cancelled) return;
        mutedUntil.current = performance.now() + 750;
        video()?.pause();
        setStatus("Disconnected");
        if (event.code === 1008 || event.code === 1009) { setError("Room/session authorization ended. Leave before creating or joining again."); return; }
        appliedContent.current = 0;
        retryTimer = window.setTimeout(connect, 1500);
      };
    }
    connect();
    const interval = window.setInterval(() => {
      const v = video();
      if (v && resetRateAt.current && performance.now() >= resetRateAt.current) { v.playbackRate = 1; resetRateAt.current = 0; }
      if (v && !resolving.current && current.current) {
        if (appliedContent.current !== current.current.content_revision) return;
        if (v.readyState >= 2 && !current.current.participants.find(p => p.id === participant.current)?.ready) send("ready");
        else send("position", { position: v.currentTime, rate_supported: rateSupported.current });
      }
    }, 2000);
    // Native player controls are host intent. Programmatic corrections never echo.
    const control = (event: Event) => {
      const v = video(), state = current.current;
      if (v && event.target === v && event.type === "canplay" && state && !resolving.current && appliedContent.current === state.content_revision && alignedSource.current !== currentSource.current) {
        alignedSource.current = currentSource.current;
        enforce(state.state,state.position,"seek");
        if (!state.participants.find(p => p.id === participant.current)?.ready) send("ready");
        return;
      }
      if (!v || event.target !== v || !state || resolving.current || performance.now() < mutedUntil.current || state.host_id !== participant.current) return;
      if (event.type === "play" && state.state !== "playing") send("play", { position: v.currentTime });
      if (event.type === "pause" && !v.ended && state.state !== "paused") send("pause", { position: v.currentTime });
      if (event.type === "ended" && state.state !== "paused") send("pause", { position: v.currentTime });
      if (event.type === "seeked") send("seek", { position: v.currentTime });
    };
    for (const type of ["play","pause","seeked","canplay","ended"]) document.addEventListener(type, control, true);
    return () => {
      cancelled = true; window.clearInterval(interval); window.clearTimeout(retryTimer); ws?.close();
      for (const type of ["play","pause","seeked","canplay","ended"]) document.removeEventListener(type, control, true);
      const v = video(); if (v) v.playbackRate = 1;
    };
  }, [roomId, retry, props.clientId]);

  useEffect(() => {
    if (roomId && props.sourceId !== currentSource.current) {
      currentSource.current = props.sourceId;
      send("preferences_changed");
    }
  }, [props.sourceId, roomId]);

  const host = room?.host_id === participant.current;
  return <section className="panel">
    <h2>Watch Together</h2>
    {!roomId ? <>
      <button onClick={() => void enter(true)}>Create room</button>
      <label>Room ID <input value={code} onChange={e => setCode(e.target.value)} maxLength={64} /></label>
      <button disabled={!code.trim()} onClick={() => void enter(false)}>Join room</button>
    </> : <>
      <p>Room: <code>{roomId}</code> · {status} · {host ? "Host" : "Participant"} · revision {room?.revision}</p>
      <p>{room?.participants.map(p => `${p.name}${p.id === room.host_id ? " (host)" : ""}: ${p.connected ? p.ready ? "ready" : "preparing" : "disconnected"}`).join(" · ")}</p>
      <button disabled={!host} onClick={() => send("play")}>Play room</button>
      <button disabled={!host} onClick={() => send("pause")}>Pause room</button>
      <button disabled={!host} onClick={() => send("seek", { position: document.querySelector<HTMLVideoElement>(".playback-stage video")?.currentTime ?? 0 })}>Sync room to my position</button>
      <button disabled={!host || room?.content.media_type !== "tv"} onClick={() => send("next_episode")}>Next episode for room</button>
      <button onClick={() => { appliedContent.current = 0; setRetry(v => v+1); }}>Reconnect / retry source</button>
      <button onClick={() => send("leave")}>Leave room</button>
      <button disabled={!host} onClick={() => send("close")}>Close room</button>
      <button onClick={detach}>Disconnect locally</button>
      <small>{debug}</small>
    </>}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
