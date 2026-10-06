import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError, getGenreItems, type FeedItem } from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";
import MediaCard from "./MediaCard";
import MediaCardSkeleton from "./MediaCardSkeleton";

type Scope = "all" | "movie" | "tv";

export default function GenrePage() {
  const { profile } = useProfile();
  const { genreId } = useParams();
  const [params, setParams] = useSearchParams();
  const t = useText();
  const id = Number(genreId);
  const scope: Scope = params.get("scope") === "movie" ? "movie" : params.get("scope") === "tv" ? "tv" : "all";
  const [title, setTitle] = useState("");
  const [items, setItems] = useState<FeedItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const request = useRef(false);
  const generation = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const load = useCallback(async (next?: string) => {
    if (!profile || !Number.isInteger(id) || id <= 0 || request.current) return;
    request.current = true;
    const sequence = generation.current;
    setBusy(true); setError("");
    try {
      const page = await getGenreItems(id, scope, next);
      if (sequence !== generation.current) return;
      setTitle(page.title);
      setItems(old => {
        const existing = new Set(next ? old.map(item => item.key) : []);
        return [...(next ? old : []), ...page.results.filter(item => !existing.has(item.key))];
      });
      setCursor(page.next_cursor);
      setLoaded(true);
    } catch (reason) {
      if (sequence !== generation.current) return;
      if (next && reason instanceof ApiError && [409, 410].includes(reason.status)) {
        request.current = false; setBusy(false); setItems([]); setCursor(null); void load(); return;
      }
      setError(reason instanceof Error ? reason.message : "The catalog is temporarily unavailable.");
    } finally { if (sequence === generation.current) { request.current = false; setBusy(false); } }
  }, [id, profile?.id, scope]);
  useEffect(() => {
    generation.current++;
    setTitle(""); setItems([]); setCursor(null); setLoaded(false);
    request.current = false;
    void load();
    return () => { generation.current++; request.current = false; };
  }, [load]);
  useEffect(() => {
    if (!cursor || busy || error || !sentinel.current) return;
    const observer = new IntersectionObserver(entries => { if (entries[0].isIntersecting) { observer.disconnect(); void load(cursor); } }, { rootMargin: "450px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [cursor, busy, error, load]);
  if (!profile) return <ProfileSelection />;
  return <div className="product-shell ambient subtle"><AppHeader /><main className="product-page genre-page" id="main-content">
    <header className="genre-page-header"><span className="orbis-kicker">ORBIS / {t("Browse by genre")}</span><h1>{title || t("Browse by genre")}</h1>
      <div className="filter-tabs" role="group" aria-label={t("Content type")}>{(["all", "movie", "tv"] as Scope[]).map(value =>
        <button type="button" key={value} className={scope === value ? "selected" : ""} aria-pressed={scope === value}
          onClick={() => setParams({ scope: value })}>{t(value === "all" ? "All" : value === "movie" ? "Movies" : "Series")}</button>)}</div>
    </header>
    <div className="genre-grid">{items.map(item => <MediaCard key={item.key} item={item} />)}
      {busy && !items.length ? Array.from({ length: 12 }, (_, index) => <MediaCardSkeleton key={index} />) : null}</div>
    {error ? <div className="product-state" role="alert"><p>{t(error)}</p><button className="orbis-button" onClick={() => void load(cursor ?? undefined)}>{t("Try again")}</button></div> : null}
    {loaded && !busy && !error && !items.length ? <div className="product-state">{t("No titles yet")}</div> : null}
    <div ref={sentinel} className="shelf-sentinel" />
    {cursor ? <button type="button" className="load-shelves" disabled={busy} onClick={() => void load(cursor)}>{t(busy ? "Loading more" : "Load more")}</button> : null}
  </main></div>;
}
