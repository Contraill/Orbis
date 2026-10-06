import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { catalogCredits, searchGenres, unifiedSearch, type GenreSearchResult, type SearchResult } from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";
import MediaCardSkeleton from "./MediaCardSkeleton";

const groups = ["movie", "tv", "person", "company"] as const;
type Group = typeof groups[number] | "all";

export default function SearchPage() {
  const { profile } = useProfile();
  const t = useText();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [kind, setKind] = useState<Group>("all");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [genreResults, setGenreResults] = useState<GenreSearchResult[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [credit, setCredit] = useState<SearchResult | null>(null);
  const [online, setOnline] = useState(false);
  const [retry, setRetry] = useState(0);
  const sequence = useRef(0);
  const locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const previous = useRef<{ results: SearchResult[]; cursor: string | null; online: boolean } | null>(null);

  useEffect(() => {
    const q = query.trim();
    const id = ++sequence.current;
    controller.current?.abort();
    setCredit(null); setOnline(false); setResults([]); setGenreResults([]); setCursor(null); setError("");
    if (q.length < 2 || !profile) { setBusy(false); return; }
    setBusy(true);
    const abort = new AbortController(); controller.current = abort;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const [local, genres] = await Promise.all([
          unifiedSearch(q, kind, false, undefined, abort.signal),
          kind === "all" || kind === "movie" || kind === "tv"
            ? searchGenres(q, kind, abort.signal).then(page => page.results).catch(() => [] as GenreSearchResult[])
            : Promise.resolve([] as GenreSearchResult[]),
        ]);
        if (id !== sequence.current) return;
        let page = local;
        let enriched = false;
        if (!local.results.length && !genres.length && q.length >= 3) { page = await unifiedSearch(q, kind, true, undefined, abort.signal); enriched = true; }
        if (id !== sequence.current) return;
        setGenreResults(genres);
        setResults(page.results); setCursor(page.next_cursor); setOnline(enriched);
        setParams(q ? { q } : {}, { replace: true });
      } catch (reason) { if (id === sequence.current && !abort.signal.aborted) setError(reason instanceof Error ? reason.message : t("Request failed")); }
      finally { if (id === sequence.current) setBusy(false); }
    }, 360);
    return () => { window.clearTimeout(timer); abort.abort(); };
  }, [query, kind, profile?.id, profile?.locale, retry]);

  async function more() {
    if (!cursor || locked.current) return;
    locked.current = true; setBusy(true); setError("");
    const id = sequence.current;
    try {
      const page = credit ? await catalogCredits(credit.kind as "person" | "company", credit.tmdb_id, cursor) : await unifiedSearch(query.trim(), kind, online, cursor);
      if (id !== sequence.current) return;
      setResults(old => { const keys = new Set(old.map(i => i.key)); return [...old, ...page.results.filter(i => !keys.has(i.key))]; });
      setCursor(page.next_cursor);
    } catch (reason) { if (id === sequence.current) setError(reason instanceof Error ? reason.message : t("Request failed")); }
    finally { locked.current = false; if (id === sequence.current) setBusy(false); }
  }

  async function showCredits(person: SearchResult) {
    if (locked.current || (person.kind !== "person" && person.kind !== "company")) return;
    locked.current = true; const id = ++sequence.current;
    previous.current = { results, cursor, online };
    setCredit(person); setBusy(true); setError(""); setResults([]); setCursor(null);
    try {
      let page = await catalogCredits(person.kind, person.tmdb_id);
      if (!page.results.length && person.kind === "person") page = await catalogCredits(person.kind, person.tmdb_id, undefined, true);
      if (id === sequence.current) { setResults(page.results); setCursor(page.next_cursor); }
    }
    catch (reason) { if (id === sequence.current) setError(reason instanceof Error ? reason.message : t("Request failed")); }
    finally { locked.current = false; if (id === sequence.current) setBusy(false); }
  }
  async function expandOnline() {
    if (locked.current || query.trim().length < 3) return;
    locked.current = true; setBusy(true); setError("");
    const id = sequence.current;
    try {
      const page = await unifiedSearch(query.trim(), kind, true);
      if (id === sequence.current) { setResults(page.results); setCursor(page.next_cursor); setOnline(true); }
    } catch (reason) { if (id === sequence.current) setError(reason instanceof Error ? reason.message : t("Request failed")); }
    finally { locked.current = false; if (id === sequence.current) setBusy(false); }
  }
  function backToResults() {
    sequence.current++;
    setCredit(null);
    setResults(previous.current?.results ?? []);
    setCursor(previous.current?.cursor ?? null);
    setOnline(previous.current?.online ?? false);
    setBusy(false); setError("");
  }
  if (!profile) return <ProfileSelection />;
  return <div className="product-shell ambient"><AppHeader /><main className="product-page search-page">
    <div className="page-heading"><span className="orbis-kicker">ORBIS / {t("Search")}</span><h1>{credit ? credit.title : t("Search Orbis")}</h1><p>{credit ? credit.roles.map(t).join(" · ") : t("Search titles, genres, people and studios")}</p></div>
    {credit ? <button className="quiet-action" onClick={backToResults}>{t("Back to results")}</button> : <>
      <label className="search-field"><span aria-hidden="true">⌕</span><input autoFocus type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder={t("Search titles, genres, people and studios")} maxLength={200} aria-label={t("Search Orbis")} /></label>
      <div className="filter-tabs" role="group" aria-label={t("Search")}>{(["all", ...groups] as Group[]).map(value => <button key={value} className={kind === value ? "selected" : ""} onClick={() => setKind(value)}>{t(value === "all" ? "All" : value === "movie" ? "Movies" : value === "tv" ? "Series" : value === "person" ? "People" : "Companies")}</button>)}</div>
    </>}
    {busy && !results.length ? <div className="search-grid search-skeleton" role="status" aria-label={t("Loading…")}>{Array.from({ length: 4 }, (_, index) => <MediaCardSkeleton compact key={index} />)}</div> : null}
    {error ? <div className="product-state" role="alert">{error}<button className="orbis-button" onClick={() => setRetry(current => current + 1)}>{t("Try again")}</button></div> : null}
    {!busy && !error && !results.length && !genreResults.length ? <div className="product-state"><h2>{query.length < 2 && !credit ? t("Start with a title, genre, person or studio") : t("No results found")}</h2><p>{query.length < 2 && !credit ? t("Search across languages and discover the people behind what you love.") : t("Try another spelling or a different title.")}</p></div> : null}
    {!credit && genreResults.length ? <section className="search-group"><h2>{t("Genres")}</h2><div className="search-grid">{genreResults.map(genre =>
      <Link className="search-hit genre-hit" key={`${genre.scope}:${genre.genre_id}`} to={`/genre/${genre.genre_id}?scope=${genre.scope}`}>
        <span className="genre-glyph" aria-hidden="true">◇</span><span><strong>{genre.title}</strong><small>{t("Explore genre")}</small></span><span aria-hidden="true">↗</span>
      </Link>)}</div></section> : null}
    {groups.map(group => { const items = results.filter(i => i.kind === group); if (!items.length) return null;
      return <section className="search-group" key={group}><h2>{t(group === "movie" ? "Movies" : group === "tv" ? "Series" : group === "person" ? "People" : "Companies")}</h2>
        <div className="search-grid">{items.map(item => item.kind === "movie" || item.kind === "tv"
          ? <Link className="search-hit" key={item.key} to={`/${item.kind}/${item.tmdb_id}`}><span className="search-hit-art"><span>{item.title[0]}</span>{item.poster_url ? <img src={item.poster_url} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true; }} /> : null}</span><span><strong>{item.title}</strong><small>{item.roles.length ? item.roles.map(t).join(" · ") : item.release_date?.slice(0, 4) || t(item.kind === "movie" ? "Movies" : "Series")}</small></span></Link>
          : <button className="search-hit person-hit" key={item.key} onClick={() => void showCredits(item)}><span className="person-glyph" aria-hidden="true">{item.title[0]}</span><span><strong>{item.title}</strong><small>{item.roles.map(t).join(" · ") || t("Discover credits")}</small></span><span aria-hidden="true">↗</span></button>)}</div>
      </section>; })}
    {!credit && !online && query.trim().length >= 3 && (results.length > 0 || genreResults.length > 0) ? <button className="quiet-action search-expand" disabled={busy} onClick={() => void expandOnline()}>{t("Search wider catalog")} ↗</button> : null}
    {cursor ? <button className="load-shelves" disabled={busy} onClick={() => void more()}>{t("Load more")} ↓</button> : null}
  </main></div>;
}
