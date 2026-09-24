import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getFeed, getFeedDiagnostics, setListIntent, hideContinue, type FeedItem, type FeedShelf, type FeedSurface, ApiError } from "../api";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import MediaCard from "./MediaCard";

export default function FeedVerification({ surface }: { surface: FeedSurface }) {
  const { profile, admin } = useProfile();
  const t = useText();
  const [shelves, setShelves] = useState<FeedShelf[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState("");
  const [busy, setBusy] = useState(false);
  const [personalized, setPersonalized] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [diagnostics, setDiagnostics] = useState<unknown>(null);
  const generation = useRef(0);
  const currentProfile = profile?.id;

  async function load(next?: string) {
    if (!currentProfile) return;
    const id = ++generation.current;
    setBusy(true); setError("");
    if (!next) { setShelves([]); setCursor(null); setDiagnostics(null); }
    try {
      const page = await getFeed(currentProfile, surface, next);
      if (id !== generation.current) return;
      setShelves(old => next ? [...old, ...page.shelves] : page.shelves);
      setCursor(page.next_cursor); setSnapshot(page.snapshot_id);
      setPersonalized(page.personalized); setWarnings(page.warnings);
    } catch (reason) {
      if (id !== generation.current) return;
      setError(reason instanceof ApiError && [409, 410].includes(reason.status)
        ? "This feed changed or expired. Refresh to start a new feed." : String(reason));
    } finally {
      if (id === generation.current) setBusy(false);
    }
  }
  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [currentProfile, profile?.locale, surface]);

  async function feedback(item: FeedItem, negative: boolean) {
    if (!currentProfile) return;
    const id = ++generation.current;
    setBusy(true); setError("");
    try {
      await setListIntent(currentProfile, item, true, negative);
      if (id === generation.current) await load();
    } catch (reason) {
      if (id === generation.current) { setError(String(reason)); setBusy(false); }
    }
  }
  async function hide(item: FeedItem) {
    if (!currentProfile) return;
    const id = ++generation.current;
    setBusy(true); setError("");
    try {
      await hideContinue(currentProfile, item);
      if (id === generation.current) await load();
    } catch (reason) {
      if (id === generation.current) { setError(String(reason)); setBusy(false); }
    }
  }
  if (!profile) return null;
  return <section aria-label="Feed verification">
    <p>{personalized ? "Using your selections and meaningful viewing" : "Catalog discovery — no established taste yet"}</p>
    <button className="button secondary" disabled={busy} onClick={() => void load()}>Refresh feed</button>
    {error ? <p className="banner error-banner" role="alert">{error}</p> : null}
    {warnings.length ? <details><summary>Catalog availability</summary>{warnings.map(w => <p key={w}>{w}</p>)}</details> : null}
    {shelves.map(shelf => <section className="catalog-section" key={shelf.id} data-shelf-id={shelf.id}>
      <h2>{shelf.title}</h2>
      <div className="media-grid">{shelf.items.map(item => <article key={item.key}>
        <MediaCard item={item} />
        {item.resume ? <div><Link className="button primary link-button" to={`/watch/${profile.id}/${item.media_type}/${item.tmdb_id}` + (item.media_type === "tv" ? `/season/${item.resume.season_number}/episode/${item.resume.episode_number}` : "")}>{t(item.resume.action === "next_episode" ? "Next episode" : "Resume")}</Link><button className="button secondary" disabled={busy} onClick={() => void hide(item)}>{t("Remove from Continue Watching")}</button></div> : <div className="foundation-actions">
          <button className="button secondary" disabled={busy} onClick={() => void feedback(item, true)}>{t("Not Interested")}</button>
          <button className="button secondary" disabled={busy} onClick={() => void feedback(item, false)}>{t("Add to My List")}</button>
        </div>}
      </article>)}</div>
    </section>)}
    {busy ? <p role="status">{t("Loading…")}</p> : null}
    {!busy && !error && !shelves.length ? <p>No eligible cached titles yet. Add onboarding selections or browse/search to enrich the catalog.</p> : null}
    {cursor ? <button className="button primary" disabled={busy} onClick={() => void load(cursor)}>Load more shelves</button> : shelves.length && !busy ? <p>End of this feed</p> : null}
    {snapshot && admin ? <details><summary>Recommendation diagnostics (verification)</summary>
      <button className="button secondary" disabled={busy} onClick={async () => {
        const id = generation.current;
        try { const value = await getFeedDiagnostics(profile.id, snapshot); if (id === generation.current) setDiagnostics(value); }
        catch (reason) { if (id === generation.current) setError(String(reason)); }
      }}>Load scoring details</button>
      {diagnostics ? <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(diagnostics, null, 2)}</pre> : null}
    </details> : null}
  </section>;
}
