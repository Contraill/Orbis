import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { editProfile, unifiedSearch } from "../api";
import type { CatalogItem, ContentSelection } from "../types";
import { invalidateFeedCache } from "../catalog/InfiniteShelfFeed";
import { useProfile } from "./ProfileContext";
import { translate, useText } from "./i18n";

export const pendingTasteKey = (id: number) => `orbis.pending-taste.${id}`;

export default function TasteSelection() {
  const { id } = useParams();
  const { profile, reload } = useProfile();
  const navigate = useNavigate();
  const t = useText();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CatalogItem[]>([]);
  const [selected, setSelected] = useState<CatalogItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [immediate, setImmediate] = useState(0);
  const submittedQuery = useRef("");
  const searchSequence = useRef(0);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!profile || String(profile.id) !== id || localStorage.getItem(pendingTasteKey(profile.id)) !== "1") return;
    const q = query.trim();
    const sequence = ++searchSequence.current;
    const controller = new AbortController();
    setError(""); setResults([]);
    if (q.length < 2) { setSearching(false); return () => controller.abort(); }
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const run = async (online: boolean) => (await unifiedSearch(q, "all", online, undefined, controller.signal)).results.filter(item => item.kind === "movie" || item.kind === "tv").map(item => ({ ...item, media_type: item.kind as "movie" | "tv", original_title: null, overview: item.overview ?? "", poster_url: item.poster_url ?? null, backdrop_url: item.backdrop_url ?? null, release_date: item.release_date ?? null, vote_average: item.vote_average ?? null }));
        const local = await run(false);
        const found = local.length ? local : await run(true);
        if (sequence === searchSequence.current) setResults(found);
      } catch { if (sequence === searchSequence.current && !controller.signal.aborted) setError(translate(profile.locale, "Search is temporarily unavailable.")); }
      finally { if (sequence === searchSequence.current) setSearching(false); }
    }, immediate && q === submittedQuery.current ? 0 : 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, immediate, profile?.id, profile?.locale, id]);
  function search(event: FormEvent) { event.preventDefault(); if (query.trim().length >= 2) { submittedQuery.current = query.trim(); setImmediate(value => value + 1); } }
  function toggle(item: CatalogItem) {
    const key = `${item.media_type}:${item.tmdb_id}`;
    setSelected(current => current.some(value => `${value.media_type}:${value.tmdb_id}` === key) ? current.filter(value => `${value.media_type}:${value.tmdb_id}` !== key) : current.length < 5 ? [...current, item] : current);
  }
  async function finish(skip = false) {
    if (!profile || saving) return;
    setSaving(true); setError("");
    try {
      const seeds: ContentSelection[] = skip ? [] : selected.map(item => ({ media_type: item.media_type, tmdb_id: item.tmdb_id }));
      if (seeds.length) await editProfile(profile.id, { onboarding_seeds: seeds });
      localStorage.removeItem(pendingTasteKey(profile.id));
      invalidateFeedCache(profile.id);
      await reload();
      navigate("/", { replace: true });
    } catch { setError(t("Could not save your choices. Try again.")); }
    finally { setSaving(false); }
  }
  if (!profile || String(profile.id) !== id || localStorage.getItem(pendingTasteKey(profile.id)) !== "1") return <Navigate to="/" replace />;
  return <main className="product-shell ambient taste-page"><section className="taste-inner panel">
    <img className="setup-brand" src="/brand/wordmark.png" alt="Orbis" />
    <span className="orbis-kicker">{t("Make Orbis your own")}</span>
    <h1>{t("Up to five favorites")}</h1><p>{t("Pick films and series you love to shape your first recommendations.")}</p>
    <form className="taste-search" onSubmit={search}><label>{t("Search")}<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t("Search titles, people and studios")} /></label></form>
    <p className="selection-count" aria-live="polite">{t("Selected")}: {selected.length} / 5</p>
    {selected.length ? <div className="taste-selected">{selected.map(item => <button key={`${item.media_type}:${item.tmdb_id}`} type="button" onClick={() => toggle(item)}>{item.title} ×</button>)}</div> : null}
    {searching ? <p role="status" className="taste-search-status">{t("Loading…")}</p> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    <div className="onboarding-grid taste-grid">{results.map(item => { const active = selected.some(value => value.media_type === item.media_type && value.tmdb_id === item.tmdb_id); return <button key={`${item.media_type}:${item.tmdb_id}`} type="button" className={`onboarding-card ${active ? "selected" : ""}`} aria-pressed={active} disabled={saving || (!active && selected.length >= 5)} onClick={() => toggle(item)}><span>{item.poster_url ? <img src={item.poster_url} alt="" loading="lazy" /> : item.title.slice(0, 1)}</span><strong>{item.title}</strong><small aria-hidden="true">{active ? "✓" : "+"}</small></button>; })}</div>
    <div className="wizard-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => void finish(true)}>{t("Skip for now")}</button><button className="button primary" type="button" disabled={saving} onClick={() => void finish()}>{t("Finish")}</button></div>
  </section></main>;
}
