import { useEffect, useRef, useState, type FormEvent } from "react";
import { getTrending, searchCatalog } from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import type { CatalogItem } from "../types";
import MediaCard from "./MediaCard";
import ProfileSelection from "./ProfileSelection";
import { ContinueShelf } from "./LibraryPage";

export default function HomePage() {
  const { profile } = useProfile(); const t = useText();
  const [trending, setTrending] = useState<CatalogItem[]>([]);
  const [results, setResults] = useState<CatalogItem[]>([]);
  const [query, setQuery] = useState("");
  const [searchTitle, setSearchTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  useEffect(() => {
    if (!profile) return;
    let cancelled = false; setLoading(true); setError("");
    getTrending().then(page => { if (!cancelled) setTrending(page.results); })
      .catch(reason => { if (!cancelled) setError(String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; requestId.current += 1; };
  }, [profile?.id]);
  async function search(event: FormEvent) {
    event.preventDefault(); const value = query.trim(); if (!value) return;
    const id = ++requestId.current; setSearchTitle(value); setSearching(true); setError(""); setResults([]);
    try { const page = await searchCatalog(value); if (id === requestId.current) setResults(page.results); }
    catch (reason) { if (id === requestId.current) setError(String(reason)); }
    finally { if (id === requestId.current) setSearching(false); }
  }
  if (!profile) return <ProfileSelection />;
  return <div className="catalog-shell"><AppHeader /><main className="catalog-main">
    <section className="catalog-hero"><p className="eyebrow">ORBIS · {profile.name}</p><h1>{t("Browse")}</h1>
      <form className="catalog-search" onSubmit={search}>
        <label className="sr-only" htmlFor="catalog-query">{t("Search")}</label>
        <input id="catalog-query" type="search" value={query} placeholder={t("Search")} onChange={e => setQuery(e.target.value)} />
        <button className="button primary" type="submit">{t("Search")}</button>
        {searchTitle ? <button className="button secondary" type="button" onClick={() => { requestId.current += 1; setQuery(""); setSearchTitle(""); setSearching(false); setError(""); }}>{t("Back")}</button> : null}
      </form>
    </section>
    {!searchTitle ? <ContinueShelf /> : null}
    <section className="catalog-section"><div className="catalog-section-heading"><h2>{searchTitle || t("Trending today")}</h2></div>
      {searching || (!searchTitle && loading) ? <p className="catalog-status">{t("Loading…")}</p> : null}
      {error ? <p className="banner error-banner" role="alert">{error}</p> : null}
      {!loading && !searching && !(searchTitle ? results : trending).length ? <p className="empty-state">{t("Nothing here yet")}</p> : null}
      <div className="media-grid">{(searchTitle ? results : trending).map(item => <MediaCard key={item.media_type + ":" + item.tmdb_id} item={item} />)}</div>
    </section>
  </main></div>;
}
