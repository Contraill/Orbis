import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getMyList, setListIntent } from "../api";
import type { LibraryItem } from "../types";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";
import { invalidateFeedCache } from "./InfiniteShelfFeed";

export default function MyListPage() {
  const { profile } = useProfile();
  const t = useText();
  const [kind, setKind] = useState("all");
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [visible, setVisible] = useState(24);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!profile) return;
    let current = true;
    setBusy(true); setError(""); setVisible(24);
    getMyList(profile.id, kind).then(value => { if (current) setItems(value); }).catch(reason => { if (current) setError(reason instanceof Error ? reason.message : t("Request failed")); }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [profile?.id, profile?.locale, kind, refresh]);
  if (!profile) return <ProfileSelection />;
  async function remove(item: LibraryItem) {
    if (!profile) return;
    setBusy(true); setError("");
    try { await setListIntent(profile.id, { media_type: item.media_type, tmdb_id: item.tmdb_id }, false); invalidateFeedCache(profile.id); setItems(current => current.filter(i => i.media_type !== item.media_type || i.tmdb_id !== item.tmdb_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("Request failed")); }
    finally { setBusy(false); }
  }
  return <div className="product-shell ambient"><AppHeader />
    <main className="product-page list-page"><div className="page-heading"><span className="orbis-kicker">ORBIS / {t("My List")}</span><h1>{t("Your collection")}</h1><p>{t("Only the titles you saved.")}</p></div>
      <div className="filter-tabs" role="group" aria-label={t("My List")}>
        {(["all", "movie", "tv"] as const).map(value => <button key={value} className={kind === value ? "selected" : ""} onClick={() => setKind(value)}>{t(value === "all" ? "All" : value === "movie" ? "Movies" : "Series")}</button>)}
      </div>
      {error ? <div className="product-state" role="alert">{error}<button className="orbis-button" onClick={() => setRefresh(current => current + 1)}>{t("Try again")}</button></div> : null}
      {busy && !items.length ? <p role="status">{t("Loading…")}</p> : null}
      {!busy && !items.length && !error ? <div className="product-state"><h2>{t("No titles yet")}</h2><p>{t("Your saved titles will appear here.")}</p><Link className="orbis-button" to="/search">{t("Search Orbis")}</Link></div> : null}
      <div className="list-grid">{items.slice(0, visible).map(item => <article className="list-card" key={`${item.media_type}:${item.tmdb_id}`}>
        <Link to={`/${item.media_type}/${item.tmdb_id}`} className="list-card-art">{item.metadata?.poster_url ? <img src={item.metadata.poster_url} alt="" loading="lazy" /> : <span>{item.metadata?.title.slice(0, 1)}</span>}</Link>
        <div><Link to={`/${item.media_type}/${item.tmdb_id}`}>{item.metadata?.title ?? t("Saved title")}</Link><small>{t(item.media_type === "movie" ? "Movies" : "Series")}{item.metadata?.release_date ? ` · ${item.metadata.release_date.slice(0, 4)}` : ""}</small></div>
        <button className="quiet-action" disabled={busy} onClick={() => void remove(item)} aria-label={`${t("Remove from My List")}: ${item.metadata?.title ?? item.tmdb_id}`}>{t("Remove")}</button>
      </article>)}</div>
      {items.length > visible ? <button className="load-shelves" onClick={() => setVisible(current => current + 24)}>{t("Load more")} ↓</button> : null}
    </main>
  </div>;
}
