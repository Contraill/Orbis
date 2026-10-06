import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getContinue, getFeed, hideContinue, type FeedItem, type FeedShelf, type FeedSurface } from "../api";
import { useText } from "../app/i18n";
import MediaCard from "./MediaCard";
import MediaCardSkeleton from "./MediaCardSkeleton";

type Cache = { shelves: FeedShelf[]; cursor: string | null; savedAt: number };
const pageCache = new Map<string, Cache>();
export function invalidateFeedCache(profileId?: number) {
  for (const key of pageCache.keys()) if (profileId == null || key.startsWith(`${profileId}:`)) pageCache.delete(key);
}
const cacheKey = (profileId: number, locale: string, surface: string) => `${profileId}:${locale}:${surface}`;

function ContinueCard({ item, duration, onHide }: { item: FeedItem; duration: number | null; onHide: () => Promise<void> }) {
  const t = useText();
  const position = item.resume?.position_seconds ?? 0;
  return <article className="orbis-continue-card">
    <Link className="orbis-continue-art" to={`/${item.media_type}/${item.tmdb_id}`}>
      {item.backdrop_url || item.poster_url ? <img src={item.backdrop_url ?? item.poster_url ?? ""} alt="" loading="lazy" /> : <span>{item.title.slice(0, 1)}</span>}
      {duration && duration > 0 ? <span className="progress-track" aria-hidden="true"><span style={{ width: `${Math.min(100, position / duration * 100)}%` }} /></span> : null}
    </Link>
    <div className="orbis-continue-copy"><Link to={`/${item.media_type}/${item.tmdb_id}`}>{item.title}</Link>
      <small>{item.media_type === "tv" && item.resume?.season_number != null ? `S${item.resume.season_number} · E${item.resume.episode_number}` : `${Math.floor(position / 60)} ${t("min watched")}`}</small>
      <button className="quiet-action" onClick={() => void onHide()}>{t("Remove from Continue Watching")}</button>
    </div>
  </article>;
}

function Shelf({ shelf, durations, onHide }: { shelf: FeedShelf; durations: Record<string, number | null>; onHide: (item: FeedItem) => Promise<void> }) {
  if (!shelf.items.length) return null;
  return <section className="orbis-shelf" data-shelf-id={shelf.id} aria-label={shelf.title}>
    <div className="orbis-shelf-heading"><h2>{shelf.genre_id ? <Link className="genre-heading-link" to={`/genre/${shelf.genre_id}?scope=${shelf.genre_scope ?? "all"}`}>{shelf.title}<span aria-hidden="true">›</span></Link> : shelf.title}</h2><span aria-hidden="true" /></div>
    <div className={shelf.kind === "continue" ? "orbis-shelf-track continue-track" : "orbis-shelf-track"}>
      {shelf.items.map(item => shelf.kind === "continue"
        ? <ContinueCard key={item.key} item={item} duration={durations[item.key] ?? null} onHide={() => onHide(item)} />
        : <MediaCard key={item.key} item={item} />)}
    </div>
  </section>;
}

export default function InfiniteShelfFeed({ profileId, locale, surface, fallbackTitle }: { profileId: number; locale: string; surface: FeedSurface; fallbackTitle: string }) {
  const t = useText();
  const key = cacheKey(profileId, locale, surface);
  const cached = pageCache.get(key);
  const initial = cached && Date.now() - cached.savedAt < 120000 ? cached : null;
  const [shelves, setShelves] = useState<FeedShelf[]>(initial?.shelves ?? []);
  const [cursor, setCursor] = useState<string | null>(initial?.cursor ?? null);
  const [loaded, setLoaded] = useState(Boolean(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [durations, setDurations] = useState<Record<string, number | null>>({});
  const request = useRef(false);
  const generation = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const load = useCallback(async (next?: string) => {
    if (request.current) return;
    request.current = true;
    const sequence = ++generation.current;
    setBusy(true); setError("");
    try {
      const page = await getFeed(profileId, surface, next);
      if (sequence !== generation.current) return;
      setShelves(old => {
        const ids = new Set(next ? old.map(s => s.id) : []);
        const merged = [...(next ? old : []), ...page.shelves.filter(s => !ids.has(s.id))];
        pageCache.set(key, { shelves: merged, cursor: page.next_cursor, savedAt: Date.now() });
        if (pageCache.size > 24) pageCache.delete(pageCache.keys().next().value!);
        return merged;
      });
      setCursor(page.next_cursor);
      setLoaded(true);
    } catch (reason) {
      if (sequence !== generation.current) return;
      if (next && reason instanceof ApiError && [409, 410].includes(reason.status)) {
        pageCache.delete(key); setShelves([]); setCursor(null);
        request.current = false; setBusy(false);
        void load();
        return;
      }
      setError(reason instanceof Error ? reason.message : t("The catalog is temporarily unavailable."));
    } finally {
      if (sequence === generation.current) { request.current = false; setBusy(false); }
    }
  }, [key, profileId, surface, t]);
  useEffect(() => {
    if (!initial) void load();
    return () => { generation.current++; request.current = false; };
  }, [key]);
  useEffect(() => {
    let active = true;
    const kind = surface === "movies" ? "movie" : surface === "series" ? "tv" : "all";
    getContinue(profileId, kind).then(entries => { if (active) setDurations(Object.fromEntries(entries.map(item => [`${item.media_type}:${item.tmdb_id}`, item.duration_seconds]))); }).catch(() => {});
    return () => { active = false; };
  }, [profileId, surface]);
  useEffect(() => {
    if (!cursor || !sentinel.current || busy || error) return;
    const observer = new IntersectionObserver(entries => { if (entries[0].isIntersecting) { observer.disconnect(); void load(cursor); } }, { rootMargin: "420px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [cursor, busy, error, load]);
  async function hide(item: FeedItem) {
    try {
      await hideContinue(profileId, item);
      const updated = shelves.map(shelf => shelf.kind === "continue" ? { ...shelf, items: shelf.items.filter(i => i.key !== item.key) } : shelf);
      setShelves(updated);
      pageCache.set(key, { shelves: updated, cursor, savedAt: Date.now() });
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Request failed")); }
  }
  const hero = shelves.find(s => s.kind === "hero")?.items[0];
  return <>
    <section className={`orbis-hero ${hero?.backdrop_url ? "has-art" : ""}`} style={hero?.backdrop_url ? { backgroundImage: `url("${hero.backdrop_url}")` } : undefined}>
      <div className="orbis-hero-shade" /><div className="orbis-hero-content">
        <span className="orbis-kicker">{t(surface === "home" ? "A place for every story." : surface === "movies" ? "Movies" : "Series")}</span>
        <h1>{hero?.title ?? fallbackTitle}</h1>
        <p>{hero?.overview || t("Explore films and series chosen for you.")}</p>
        {hero ? <Link className="orbis-button accent" to={`/${hero.media_type}/${hero.tmdb_id}`}>{t("Details")} <span aria-hidden="true">↗</span></Link>
          : <Link className="orbis-button accent" to="/search">{t("Search Orbis")} <span aria-hidden="true">↗</span></Link>}
      </div>
      <div className="hero-index" aria-hidden="true"><span>ORBIS</span><span>01 / 01</span></div>
    </section>
    <div className="browse-shelves">
      {shelves.filter(s => s.kind !== "hero").map(shelf => <Shelf key={shelf.id} shelf={shelf} durations={durations} onHide={hide} />)}
      {busy && !shelves.length ? <div className="shelf-skeleton" role="status" aria-label={t("Loading…")}>{Array.from({ length: 5 }, (_, i) => <MediaCardSkeleton key={i} />)}</div> : null}
      {error ? <div className="product-state" role="alert"><p>{error}</p><button className="orbis-button" onClick={() => void load(cursor ?? undefined)}>{t("Try again")}</button></div> : null}
      {!busy && !error && !shelves.length ? <div className="product-state"><h2>{t("No titles yet")}</h2><p>{t("This section is waiting for more titles. Search to discover something new.")}</p><Link className="orbis-button" to="/search">{t("Search")}</Link></div> : null}
      <div ref={sentinel} className="shelf-sentinel" />
      {cursor ? <button className="load-shelves" disabled={busy} onClick={() => void load(cursor)}>{t(busy ? "Loading more" : "More shelves")} <span aria-hidden="true">↓</span></button> : null}
    </div>
  </>;
}
