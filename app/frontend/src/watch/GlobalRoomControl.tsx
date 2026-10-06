import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { useText } from "../app/i18n";
import { normalizeJoinCode, useGlobalWatchTogether, type RoomContent } from "./GlobalWatchTogether";
import { copyText } from "./copyText";

export default function GlobalRoomControl({ embedded = false, currentContent }: { embedded?: boolean; currentContent?: RoomContent }) {
  const t = useText();
  const location = useLocation();
  const navigate = useNavigate();
  const watch = useGlobalWatchTogether();
  const [open, setOpen] = useState(embedded);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [localError, setLocalError] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const lastPath = useRef(location.pathname);
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const invite = normalizeJoinCode(params.get("join") ?? "");
    if (/^[0-9]{6}$/.test(invite)) { setCode(invite); setOpen(true); params.delete("join"); navigate({ pathname: location.pathname, search: params.toString() }, { replace: true }); }
  }, [location.pathname, location.search, navigate]);
  useEffect(() => {
    if (!open || embedded) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href]') ?? []);
      if (!focusable.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable[focusable.length - 1]?.focus(); }
      else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
    };
    document.addEventListener("keydown", onKey);
    panel.current?.querySelector<HTMLElement>("button, input")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, embedded]);
  useEffect(() => { if (!embedded && lastPath.current !== location.pathname) setOpen(false); lastPath.current = location.pathname; }, [location.pathname, embedded]);
  async function perform(operation: () => Promise<void>) {
    setBusy(true); setLocalError(""); watch.dismissError();
    try { await operation(); } catch { setLocalError(t("Could not join the room. Check the room code and try again.")); }
    finally { setBusy(false); }
  }
  async function copy(value: string) {
    if (await copyText(value)) { setCopied(t("Copied")); window.setTimeout(() => setCopied(""), 1800); }
    else setLocalError(t("Copy failed"));
  }
  const formatted = watch.room?.join_code.replace(/^(\d{3})(\d{3})$/, "$1 $2");
  const inviteLink = watch.room ? new URL(`/?join=${watch.room.join_code}`, window.location.origin).href : "";
  async function share() {
    if (!navigator.share) return;
    try { await navigator.share({ title: t("Watch Together"), url: inviteLink }); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) setLocalError(t("Copy failed")); }
  }
  return <div className={`global-watch-control ${embedded ? "embedded" : ""}`}>
    {!embedded ? <button ref={trigger} type="button" className={`global-watch-trigger ${watch.room ? "active" : ""}`} aria-expanded={open} aria-label={t("Watch Together")} onClick={() => setOpen(value => !value)}><span aria-hidden="true">◉</span><span>{t("Watch Together")}</span>{watch.room ? <small>{watch.room.participants.length}</small> : null}</button> : null}
    {open ? createPortal(<div className={`global-watch-panel orbis-player-glass ${embedded ? "embedded" : ""}`} ref={panel} role="dialog" aria-label={t("Watch Together")}>
      <div className="global-watch-panel-heading"><h2>{t("Watch Together")}</h2>{!embedded ? <button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label={t("Close menu")}>×</button> : null}</div>
      {!watch.room ? <>
        <p>{t("Watch with another Orbis profile. Each viewer keeps their own playback source.")}</p>
        <button className="orbis-button accent" type="button" disabled={busy} onClick={() => void perform(() => watch.create(currentContent ? { content: currentContent, position: document.querySelector<HTMLVideoElement>(".playback-stage video")?.currentTime ?? 0 } : undefined))}>{t("Create room")}</button>
        <form onSubmit={event => { event.preventDefault(); if (/^[0-9]{6}$/.test(normalizeJoinCode(code))) void perform(() => watch.join(normalizeJoinCode(code))); }}>
          <label htmlFor={`watch-code-${embedded ? "player" : "global"}`}>{t("Room code")}</label>
          <input id={`watch-code-${embedded ? "player" : "global"}`} value={code.replace(/^(\d{3})(\d)/, "$1 $2")} onChange={event => setCode(normalizeJoinCode(event.target.value).replace(/\D/g, "").slice(0, 6))} inputMode="numeric" pattern="[0-9 ]{6,7}" maxLength={7} autoComplete="one-time-code" placeholder="000 000" />
          <button className="orbis-button ghost" type="submit" disabled={busy || !/^[0-9]{6}$/.test(code)}>{t("Join room")}</button>
        </form>
      </> : <>
        <div className="global-watch-code"><span>{t("Room code")}</span><strong>{formatted}</strong></div>
        <div className="global-watch-copy"><button onClick={() => void copy(watch.room!.join_code)}>{copied ? t("Copied") : t("Copy room code")}</button><button onClick={() => void copy(inviteLink)}>{t("Copy invite link")}</button>{typeof navigator.share === "function" ? <button onClick={() => void share()}>{t("Share invite")}</button> : null}</div>
        {copied ? <small role="status">{copied}</small> : null}
        <p className="global-watch-status" role="status">{t(watch.status === "reconnecting" ? "Reconnecting…" : watch.status === "connected" ? "Connected" : "Connecting")}{!watch.room.content ? ` · ${t("Waiting for others…")}` : ""}</p>
        <ul className="orbis-room-participants">{watch.room.participants.map(p => <li key={p.id}><span>{p.name}</span><small>{p.id === watch.participantId && watch.status !== "connected" ? t(watch.status === "reconnecting" ? "Reconnecting…" : "Connecting") : p.connected ? watch.room!.content ? p.ready ? t("Ready") : t("Preparing") : t("Connected") : t("Disconnected")}</small></li>)}</ul>
        {embedded && watch.room.content ? <div className="orbis-room-actions"><button onClick={() => watch.send("play")}>{t("Play")}</button><button onClick={() => watch.send("pause")}>{t("Pause")}</button><button onClick={() => watch.send("seek", { position: document.querySelector<HTMLVideoElement>(".playback-stage video")?.currentTime ?? 0 })}>{t("Sync position")}</button></div> : null}
        <button className="orbis-button ghost" onClick={() => void perform(watch.leave)}>{t("Leave room")}</button>
      </>}
      {watch.error === "audio_gesture_required" && embedded ? <button className="orbis-button accent" onClick={() => {
        const video = document.querySelector<HTMLVideoElement>(".playback-stage video");
        if (!video) return;
        video.muted = false;
        void video.play().then(watch.dismissError).catch(() => { video.muted = true; });
      }}>{t("Turn on audio")}</button> : null}
      {localError || (watch.error && watch.error !== "audio_gesture_required") ? <p className="form-error" role="alert">{localError || t("Room action was not accepted. Reconnect and try again.")}</p> : null}
    </div>, embedded ? document.getElementById("global-watch-player-slot") ?? document.body : document.body) : null}
  </div>;
}
