import { useEffect, useState } from "react";
import { request, type ClientSessionView } from "../api";

export default function SessionsPage() {
  const [sessions, setSessions] = useState<ClientSessionView[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true); setError("");
    try { setSessions(await request<ClientSessionView[]>("/api/admin/sessions")); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="panel"><h2>Client sessions</h2>
    <p>Active and recent clients. Stale playback is stopped after two minutes without a heartbeat.</p>
    <button className="button secondary" disabled={busy} onClick={() => void refresh()}>Refresh</button>
    {error ? <p role="alert">{error}</p> : null}
    {sessions.map(session => <article className="panel" key={session.id}>
      <strong>{session.display_name}</strong><p>Profile {session.profile_id} · {session.client_type} · {session.state}</p>
      <p>{session.current_playback?.content_key ?? "Not playing"} · {Math.floor(session.position_seconds)}s · last seen {new Date(session.last_seen).toLocaleString()}</p>
      <button className="button secondary" disabled={busy || !!session.revoked_at} onClick={async () => {
        setBusy(true);
        try { await request(`/api/admin/sessions/${session.id}`, { method: "DELETE" }); await refresh(); }
        catch (reason) { setError(String(reason)); }
        finally { setBusy(false); }
      }}>Terminate session</button>
      <details><summary>Reported capabilities</summary><pre>{JSON.stringify(session.capabilities, null, 2)}</pre></details>
    </article>)}
    {!busy && !sessions.length ? <p>No recent sessions.</p> : null}
  </section>;
}
