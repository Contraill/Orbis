import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, ensureClientSession, request } from "../api";
import { useProfile } from "../app/ProfileContext";

export type RoomContent = { media_type: "movie" | "tv"; tmdb_id: number; season_number: number | null; episode_number: number | null };
export type RoomState = { type: "state"; room_id: string; join_code: string; revision: number; content_revision: number; content: RoomContent | null; content_key: string | null; host_id: string; status: string; state: "paused" | "playing"; position: number; rate: number; participants: { id: string; profile_id: number; name: string; connected: boolean; ready: boolean }[]; participant_id?: string };
type Status = "idle" | "connecting" | "connected" | "reconnecting" | "closed";
type ContextValue = { room: RoomState | null; participantId: string; status: Status; error: string; create: (initial?: { content: RoomContent; position: number }) => Promise<void>; join: (code: string) => Promise<void>; leave: () => Promise<void>; start: (content: RoomContent, path: string, state?: unknown, position?: number) => Promise<boolean>; send: (type: string, fields?: Record<string, unknown>) => void; dismissError: () => void };
const Context = createContext<ContextValue | null>(null);
const storedKey = "orbis.global-watch-room";
export function normalizeJoinCode(value: string) { return value.replace(/\s/g, ""); }
export function contentPath(profileId: number, content: RoomContent) { return content.media_type === "movie" ? `/watch/${profileId}/movie/${content.tmdb_id}` : `/watch/${profileId}/tv/${content.tmdb_id}/season/${content.season_number}/episode/${content.episode_number}`; }

export function GlobalWatchTogetherProvider({ children }: { children: ReactNode }) {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const location = useLocation();
  const [room, setRoom] = useState<RoomState | null>(null);
  const [roomId, setRoomId] = useState(() => sessionStorage.getItem(storedKey) ?? "");
  const [clientId, setClientId] = useState("");
  const [participantId, setParticipantId] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const roomRef = useRef<RoomState | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const clientRef = useRef("");
  const participantRef = useRef("");
  const profileRef = useRef(profile?.id ?? 0);
  const locationRef = useRef(location.pathname);
  const mutedUntil = useRef(0);
  const resetRateAt = useRef(0);
  const readyRevision = useRef(0);
  const pendingStart = useRef(false);
  const startSentRevision = useRef(0);
  const retryTimer = useRef<number | undefined>(undefined);
  const reconnectCount = useRef(0);
  locationRef.current = location.pathname;
  roomRef.current = room;
  clientRef.current = clientId;
  participantRef.current = participantId;

  const send = useCallback((type: string, fields: Record<string, unknown> = {}) => {
    const current = roomRef.current;
    // A remote state applied to the local video must not bounce back as a new command.
    if ((type === "play" && current?.state === "playing") || (type === "pause" && current?.state === "paused")) return;
    if (current && socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type, revision: current.revision, ...fields }));
  }, []);
  const clear = useCallback(() => {
    socket.current?.close(); socket.current = null;
    if (retryTimer.current) window.clearTimeout(retryTimer.current);
    sessionStorage.removeItem(storedKey);
    setRoomId(""); setRoom(null); roomRef.current = null; setParticipantId(""); setStatus("idle");
    const video = document.querySelector<HTMLVideoElement>(".playback-stage video");
    if (video) video.playbackRate = 1;
  }, []);
  const exit = useCallback(async () => {
    const id = roomRef.current?.room_id ?? roomId;
    const client = clientRef.current;
    if (id && client) {
      try { await request(`/api/watch-together/rooms/${encodeURIComponent(id)}/exit`, { method: "POST", headers: { "X-Orbis-Session": client } }); } catch { /* room may have expired */ }
    }
    clear();
  }, [roomId, clear]);
  useEffect(() => {
    const prior = profileRef.current;
    profileRef.current = profile?.id ?? 0;
    if (prior && prior !== profileRef.current && roomId) void exit();
  }, [profile?.id, roomId, exit]);
  useEffect(() => {
    if (!profile || !roomId) return;
    let cancelled = false;
    let ws: WebSocket | null = null;
    const video = () => document.querySelector<HTMLVideoElement>(".playback-stage video");
    const applyTimeline = (state: RoomState, action: string, rate = 1, duration = 0) => {
      const v = video();
      if (!v || !state.content || locationRef.current !== contentPath(profile.id, state.content) || v.readyState < 1) return;
      if (v.dataset.orbisPendingSeek) return;
      const shouldSeek = action === "seek" && !v.seeking && Math.abs(v.currentTime - state.position) >= (state.state === "paused" ? .1 : 2);
      if (shouldSeek || (state.state === "paused" && !v.paused) || (state.state === "playing" && v.paused)) mutedUntil.current = performance.now() + 800;
      // Re-seeking a media element before its previous seek completes can keep
      // MSE permanently at HAVE_METADATA even with the segment buffered.
      if (shouldSeek) v.currentTime = Math.max(0, Number.isFinite(v.duration) ? Math.min(state.position, v.duration) : state.position);
      try { v.playbackRate = rate; } catch { /* unsupported by device */ }
      resetRateAt.current = duration ? performance.now() + duration * 1000 : 0;
      if (state.state === "paused") v.pause();
      else if (v.paused && !v.ended) void v.play().catch(async reason => {
        if (reason instanceof DOMException && reason.name === "NotAllowedError") {
          v.muted = true;
          try { await v.play(); setError("audio_gesture_required"); return; }
          catch { /* some browsers also deny muted autoplay */ }
        }
        setError("autoplay_blocked");
      });
    };
    const connect = async () => {
      try {
        setStatus(reconnectCount.current ? "reconnecting" : "connecting");
        const client = await ensureClientSession(profile.id);
        if (cancelled) return;
        setClientId(client.id); clientRef.current = client.id;
        const current = await request<RoomState>(`/api/watch-together/rooms/${encodeURIComponent(roomId)}`, { headers: { "X-Orbis-Session": client.id } });
        if (cancelled) return;
        if (current.status !== "open") { clear(); setStatus("closed"); return; }
        setParticipantId(current.participant_id ?? ""); participantRef.current = current.participant_id ?? "";
        ws = new WebSocket(`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/api/watch-together/rooms/${encodeURIComponent(roomId)}/ws`);
        socket.current = ws;
        ws.onopen = () => { reconnectCount.current = 0; ws?.send(JSON.stringify({ session_id: client.id })); };
        ws.onmessage = event => {
          let value: Omit<RoomState, "type"> & { type: string; code?: string; action?: string; duration?: number; participant_id?: string };
          try { value = JSON.parse(event.data); } catch { return; }
          if (value.type === "welcome") { setParticipantId(value.participant_id ?? ""); participantRef.current = value.participant_id ?? ""; return; }
          if (value.type === "replaced") { cancelled = true; ws?.close(); setStatus("closed"); setError("connection_replaced"); return; }
          if (value.type === "error") { if (value.code !== "stale_revision") setError(value.code ?? "room_error"); return; }
          if (value.type === "sync") {
            const currentRoom = roomRef.current;
            if (currentRoom && value.revision === currentRoom.revision && value.content_revision === currentRoom.content_revision) applyTimeline({ ...currentRoom, position: value.position, state: value.state }, value.action ?? "none", value.rate, value.duration);
            return;
          }
          if (value.type !== "state") return;
          const previous = roomRef.current;
          if (previous && value.revision < previous.revision) return;
          if (value.status !== "open" || !value.participants.some(p => p.id === participantRef.current)) { clear(); setStatus("closed"); return; }
          if (!value.participants.find(p => p.id === participantRef.current)?.ready) readyRevision.current = 0;
          roomRef.current = value as RoomState; setRoom(value as RoomState);
          if (value.participants.find(p => p.id === participantRef.current)?.connected) setStatus("connected");
          // The playback action, not canplay, starts the shared timeline. HLS may
          // remain at HAVE_METADATA until play() begins fetching media segments.
          if (pendingStart.current && value.content) {
            if (value.state === "playing") pendingStart.current = false;
            else if (startSentRevision.current !== value.revision) {
              startSentRevision.current = value.revision;
              ws?.send(JSON.stringify({ type: "play", revision: value.revision, position: value.position }));
            }
          }
          if (value.content && value.content_key !== previous?.content_key) {
            readyRevision.current = 0;
            const path = contentPath(profile.id, value.content);
            if (locationRef.current !== path) navigate(path, { state: { returnTo: locationRef.current } });
          }
          if (value.content && locationRef.current === contentPath(profile.id, value.content)) applyTimeline(value as RoomState, previous?.content_key !== value.content_key || Math.abs(value.position - (video()?.currentTime ?? value.position)) >= 2 ? "seek" : "none");
        };
        ws.onclose = event => {
          if (cancelled) return;
          socket.current = null; setStatus("reconnecting");
          video()?.pause();
          if (event.code === 1008 || event.code === 1009) { setError("room_authorization_ended"); return; }
          reconnectCount.current += 1;
          retryTimer.current = window.setTimeout(connect, Math.min(5000, 1200 * reconnectCount.current));
        };
      } catch {
        if (cancelled) return;
        if (reconnectCount.current > 1) { clear(); setError("room_closed"); return; }
        reconnectCount.current += 1;
        retryTimer.current = window.setTimeout(connect, 1500);
      }
    };
    void connect();
    const mediaEvent = (event: Event) => {
      const v = video(), state = roomRef.current;
      if (!v || event.target !== v || !state?.content || locationRef.current !== contentPath(profile.id, state.content)) return;
      if (event.type === "canplay") {
        if (!v.dataset.orbisPendingSeek) applyTimeline(state, "none");
        if (readyRevision.current !== state.content_revision) { readyRevision.current = state.content_revision; send("ready"); }
        return;
      }
      if (event.type === "seeked" && v.dataset.orbisPendingSeek) {
        const target = Number(v.dataset.orbisPendingSeek);
        if (Math.abs(v.currentTime - target) <= 1) send("seek", { position: target });
        return;
      }
      if (performance.now() < mutedUntil.current) return;
      if (event.type === "seeked") send("seek", { position: v.currentTime });
    };
    for (const name of ["seeked", "canplay"]) document.addEventListener(name, mediaEvent, true);
    let lastLobbyHeartbeat = 0;
    let lastMembershipCheck = 0;
    let checkingMembership = false;
    const heartbeat = window.setInterval(() => {
      const v = video(), state = roomRef.current;
      if (!checkingMembership && clientRef.current && Date.now() - lastMembershipCheck >= 15000) {
        lastMembershipCheck = Date.now(); checkingMembership = true;
        void fetch(`/api/watch-together/rooms/${encodeURIComponent(roomId)}`, {
          headers: { "X-Orbis-Session": clientRef.current }, credentials: "same-origin", cache: "no-store",
        }).then(async response => {
          if (cancelled) return;
          if ([403, 404, 410].includes(response.status) || (response.ok && (await response.json()).status !== "open")) {
            clear(); setStatus("closed");
          }
        })
          .catch(() => { /* transient network loss belongs to WebSocket reconnect */ })
          .finally(() => { checkingMembership = false; });
      }
      if (v && resetRateAt.current && performance.now() >= resetRateAt.current) { v.playbackRate = 1; resetRateAt.current = 0; }
      if (!state?.content || !v || locationRef.current !== contentPath(profile.id, state.content) || v.readyState < 2) {
        if (Date.now() - lastLobbyHeartbeat >= 20000) { lastLobbyHeartbeat = Date.now(); send("heartbeat"); }
        return;
      }
      if (readyRevision.current !== state.content_revision) { readyRevision.current = state.content_revision; send("ready"); }
      else if (!v.dataset.orbisPendingSeek) send("position", { position: v.currentTime, rate_supported: true });
    }, 2000);
    return () => { cancelled = true; if (retryTimer.current) window.clearTimeout(retryTimer.current); ws?.close(); window.clearInterval(heartbeat); for (const name of ["seeked", "canplay"]) document.removeEventListener(name, mediaEvent, true); const v = video(); if (v) v.playbackRate = 1; };
  }, [roomId, profile?.id, clear, navigate, send]);
  const enter = useCallback(async (code?: string, initial?: { content: RoomContent; position: number }) => {
    if (!profile) return;
    setError("");
    const client = await ensureClientSession(profile.id);
    setClientId(client.id); clientRef.current = client.id;
    const value = code ? await request<RoomState>("/api/watch-together/join", { method: "POST", headers: { "X-Orbis-Session": client.id }, body: JSON.stringify({ join_code: normalizeJoinCode(code) }) })
      : await request<RoomState>("/api/watch-together/rooms", { method: "POST", headers: { "X-Orbis-Session": client.id }, body: JSON.stringify(initial ?? {}) });
    setParticipantId(value.participant_id ?? ""); participantRef.current = value.participant_id ?? "";
    setRoom(value); roomRef.current = value;
    if (initial) pendingStart.current = true;
    sessionStorage.setItem(storedKey, value.room_id); setRoomId(value.room_id);
    if (value.content && locationRef.current !== contentPath(profile.id, value.content)) navigate(contentPath(profile.id, value.content), { state: { returnTo: locationRef.current } });
  }, [profile?.id, navigate]);
  const start = useCallback(async (content: RoomContent, path: string, state?: unknown, position = 0) => {
    const current = roomRef.current;
    if (!current) { navigate(path, { state }); return true; }
    const endpoint = `/api/watch-together/rooms/${encodeURIComponent(current.room_id)}`;
    let response: RoomState;
    try {
      response = await request<RoomState>(`${endpoint}/transition`, { method: "POST", headers: { "X-Orbis-Session": clientRef.current }, body: JSON.stringify({ revision: current.revision, content, position }) });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error;
      const latest = await request<RoomState>(endpoint, { headers: { "X-Orbis-Session": clientRef.current } });
      if (latest.content_key === (content.media_type === "movie" ? `movie:${content.tmdb_id}` : `tv:${content.tmdb_id}:s${content.season_number}:e${content.episode_number}`)) {
        navigate(path, { state }); return true;
      }
      response = await request<RoomState>(`${endpoint}/transition`, { method: "POST", headers: { "X-Orbis-Session": clientRef.current }, body: JSON.stringify({ revision: latest.revision, content, position }) });
    }
    roomRef.current = response; setRoom(response); pendingStart.current = true; readyRevision.current = 0;
    navigate(path, { state });
    return true;
  }, [navigate]);
  const value = useMemo<ContextValue>(() => ({ room, participantId, status, error, create: initial => enter(undefined, initial), join: code => enter(code), leave: exit, start, send, dismissError: () => setError("") }), [room, participantId, status, error, enter, exit, start, send]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useGlobalWatchTogether() { const value = useContext(Context); if (!value) throw new Error("GlobalWatchTogetherProvider is required"); return value; }
