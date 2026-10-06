import { useEffect, useRef, useState } from "react";

const BACK_KEY = "orbis.tv.launcherHistoryDepth";

/** Only activated by a packaged TV launcher. The normal browser app does no polling. */
export default function TvConnectionGuard() {
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);
  const [cannotReturn, setCannotReturn] = useState(false);
  const retryButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (offline) retryButton.current?.focus(); }, [offline]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("orbis_tv") === "1") {
      const depth = Number(params.get("orbis_tv_back"));
      if (Number.isInteger(depth) && depth > 0) sessionStorage.setItem(BACK_KEY, String(depth));
    }
    if (!sessionStorage.getItem(BACK_KEY)) return;
    let stopped = false;
    let misses = 0;
    let request: AbortController | undefined;
    const check = async () => {
      if (document.hidden || stopped) return;
      request?.abort();
      request = new AbortController();
      try {
        const response = await fetch("/api/health", { cache: "no-store", signal: request.signal });
        const body = await response.json();
        if (!response.ok || body.status !== "ok") throw new Error("unavailable");
        misses = 0;
        if (!stopped) setOffline(false);
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
        misses += 1;
        if (misses >= 2) setOffline(true);
      }
    };
    const interval = window.setInterval(check, 30_000);
    void check();
    const visible = () => { if (!document.hidden) void check(); };
    document.addEventListener("visibilitychange", visible);
    return () => { stopped = true; request?.abort(); window.clearInterval(interval); document.removeEventListener("visibilitychange", visible); };
  }, [retry]);

  if (!offline) return null;
  return <div className="tv-connection-overlay" role="alertdialog" aria-modal="true" aria-label="Orbis server unavailable">
    <div className="tv-connection-card">
      <img src="/brand/wordmark.png" alt="Orbis" />
      <h1>Server unavailable</h1>
      <p>Orbis cannot reach its server right now.</p>
      <p>Configured server: <strong>{window.location.origin}</strong></p>
      <div className="tv-connection-actions">
        <button ref={retryButton} onClick={() => setRetry((value) => value + 1)}>Retry</button>
        <button onClick={() => {
          const depth = Number(sessionStorage.getItem(BACK_KEY));
          const steps = window.history.length - depth;
          if (depth > 0 && steps > 0) window.history.go(-steps);
          else setCannotReturn(true);
        }}>Change Server</button>
      </div>
      {cannotReturn && <p>Close and reopen the Orbis TV app to change the server.</p>}
    </div>
  </div>;
}
