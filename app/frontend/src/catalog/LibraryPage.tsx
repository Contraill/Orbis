import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getContinue, getHistory, getMyList, hideContinue, restartPlayback, setListIntent } from "../api";
import type { ContentSelection, ContinueEntry, HistoryEntry, LibraryItem } from "../types";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";

const itemKey = (item: ContentSelection) => `${item.media_type}:${item.tmdb_id}`;
function watchPath(profileId: number, item: ContentSelection & { season_number: number | null; episode_number: number | null }) {
  return `/watch/${profileId}/${item.media_type}/${item.tmdb_id}` + (item.media_type === "tv" ? `/season/${item.season_number}/episode/${item.episode_number}` : "");
}

export function ContinueShelf({ kind = "all" }: { kind?: string }) {
  const { profile } = useProfile(); const t = useText(); const navigate = useNavigate();
  const [items, setItems] = useState<ContinueEntry[]>([]);
  const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!profile) return;
    let cancelled = false; setLoading(true); setError("");
    getContinue(profile.id, kind).then(value => { if (!cancelled) setItems(value); }).catch(reason => { if (!cancelled) setError(String(reason)); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [profile?.id, kind]);
  if (!profile) return null;
  return <section className="catalog-section"><h2>{t("Continue Watching")}</h2>
    {loading ? <p>{t("Loading…")}</p> : !items.length ? <p>{t("Nothing here yet")}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    <div className="continue-grid">{items.map(item => <article className="continue-card" key={itemKey(item)}>
      <Link className="continue-art" to={`/${item.media_type}/${item.tmdb_id}`}>
        {item.metadata?.backdrop_url || item.metadata?.poster_url ? <img src={item.metadata.backdrop_url ?? item.metadata.poster_url ?? ""} alt="" loading="lazy" /> : <span>{item.metadata?.title.slice(0, 1) ?? "▶"}</span>}
        <div className="progress-track" aria-hidden="true"><span style={{ width: `${item.duration_seconds ? Math.min(100, item.position_seconds / item.duration_seconds * 100) : 0}%` }} /></div>
      </Link>
      <div className="continue-copy"><Link to={`/${item.media_type}/${item.tmdb_id}`}>{item.metadata?.title ?? `${item.media_type} #${item.tmdb_id}`}</Link>
        {item.media_type === "tv" ? <small>S{item.season_number} E{item.episode_number}</small> : null}
        <small>{Math.floor(item.position_seconds / 60)} min</small>
        <Link className="button primary link-button" to={watchPath(profile.id, item)}>{t(item.action === "next_episode" ? "Next episode" : "Resume")}</Link>
        <button className="button secondary" disabled={busy} onClick={async () => {
          setBusy(true); setError("");
          try { await restartPlayback(profile.id, { media_type: item.media_type, tmdb_id: item.tmdb_id, season_number: item.season_number, episode_number: item.episode_number }); navigate(watchPath(profile.id, item)); }
          catch (reason) { setError(String(reason)); } finally { setBusy(false); }
        }}>{t("Start Over")}</button>
        <button className="button secondary" disabled={busy} onClick={async () => {
          setBusy(true); setError("");
          try { await hideContinue(profile.id, { media_type: item.media_type, tmdb_id: item.tmdb_id }); setItems(current => current.filter(i => itemKey(i) !== itemKey(item))); }
          catch (reason) { setError(String(reason)); } finally { setBusy(false); }
        }}>{t("Remove from Continue Watching")}</button>
      </div>
    </article>)}</div>
  </section>;
}

export function ListActions({ item }: { item: ContentSelection }) {
  const { profile } = useProfile(); const t = useText();
  const [listed, setListed] = useState(false); const [busy, setBusy] = useState(true); const [error, setError] = useState("");
  useEffect(() => {
    if (!profile) return;
    let cancelled = false; setBusy(true);
    getMyList(profile.id).then(items => { if (!cancelled) setListed(items.some(i => itemKey(i) === itemKey(item))); }).catch(reason => { if (!cancelled) setError(String(reason)); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [profile?.id, item.media_type, item.tmdb_id]);
  if (!profile) return null;
  async function act(enabled: boolean, negative = false) {
    if (!profile) return;
    setBusy(true); setError("");
    try { await setListIntent(profile.id, item, enabled, negative); if (!negative) setListed(enabled); }
    catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }
  return <div className="foundation-actions">
    <button className="button secondary" disabled={busy} onClick={() => void act(!listed)}>{t(listed ? "Remove from My List" : "Add to My List")}</button>
    <button className="button secondary" disabled={busy} onClick={() => void act(true, true)}>{t("Not Interested")}</button>
    <button className="button secondary" disabled={busy} onClick={() => void act(false, true)}>{t("Clear feedback")}</button>
    {error ? <p role="alert">{error}</p> : null}
  </div>;
}

export default function LibraryPage() {
  const { profile } = useProfile(); const t = useText(); const navigate = useNavigate();
  const [kind, setKind] = useState("all"); const [items, setItems] = useState<LibraryItem[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]); const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!profile) return;
    let cancelled = false; setLoading(true); setError("");
    Promise.all([getMyList(profile.id, kind), getHistory(profile.id)]).then(([list, activity]) => { if (!cancelled) { setItems(list); setHistory(activity); } }).catch(reason => { if (!cancelled) setError(String(reason)); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [profile?.id, kind]);
  if (!profile) return <ProfileSelection />;
  return <div className="catalog-shell"><AppHeader /><main className="catalog-main"><h1>{t("Library")}</h1>
    <label htmlFor="library-kind">{t("All")}</label><select id="library-kind" value={kind} onChange={e => setKind(e.target.value)}><option value="all">{t("All")}</option><option value="movie">{t("Movies")}</option><option value="tv">{t("Series")}</option></select>
    {error ? <p role="alert">{error}</p> : null}
    <ContinueShelf kind={kind} />
    <section className="catalog-section"><h2>{t("My List")}</h2>
      {loading ? <p>{t("Loading…")}</p> : !items.length ? <p>{t("Nothing here yet")}</p> : null}
      {items.map(item => <article className="panel" key={itemKey(item)}><Link to={`/${item.media_type}/${item.tmdb_id}`}>{item.metadata?.title ?? itemKey(item)}</Link><button className="button secondary" disabled={busy} onClick={async () => {
        setBusy(true); try { await setListIntent(profile.id, { media_type: item.media_type, tmdb_id: item.tmdb_id }, false); setItems(current => current.filter(i => itemKey(i) !== itemKey(item))); } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
      }}>{t("Remove")}</button></article>)}
    </section>
    <section className="catalog-section"><h2>{t("History")}</h2>
      {!loading && !history.length ? <p>{t("Nothing here yet")}</p> : null}
      {history.filter(item => kind === "all" || item.media_type === kind).map(item => <article className="panel" key={item.content_key}>
        <Link to={`/${item.media_type}/${item.tmdb_id}`}>{item.metadata?.title ?? itemKey(item)}</Link>
        <p>{item.media_type === "tv" ? `S${item.season_number} E${item.episode_number} · ` : ""}{Math.floor(item.watched_seconds)}s · {t(item.meaningful ? "Meaningful viewing" : "Brief start")}</p>
        <small>{new Date(item.last_watched_at).toLocaleString(profile.locale)} · {t("Completions")}: {item.completions} · {t("Rewatches")}: {item.rewatches}</small>
        <button className="button secondary" disabled={busy} onClick={async () => {
          setBusy(true); try { await restartPlayback(profile.id, { media_type: item.media_type, tmdb_id: item.tmdb_id, season_number: item.season_number, episode_number: item.episode_number }); navigate(watchPath(profile.id, item)); } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
        }}>{t("Play Again")}</button>
      </article>)}
    </section>
  </main></div>;
}
