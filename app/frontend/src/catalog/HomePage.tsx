import { useEffect, useState } from "react";
import { getTrending } from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import type { CatalogItem } from "../types";
import MediaCard from "./MediaCard";
import ProfileSelection from "./ProfileSelection";
import SearchVerification from "./SearchVerification";
import { ContinueShelf } from "./LibraryPage";

export default function HomePage() {
  const { profile } = useProfile(); const t = useText();
  const [trending, setTrending] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!profile) return;
    let cancelled = false; setLoading(true); setError("");
    getTrending().then(page => { if (!cancelled) setTrending(page.results); })
      .catch(reason => { if (!cancelled) setError(String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [profile?.id, profile?.locale]);
  if (!profile) return <ProfileSelection />;
  return <div className="catalog-shell"><AppHeader /><main className="catalog-main">
    <section className="catalog-hero"><p className="eyebrow">ORBIS · {profile.name}</p><h1>{t("Browse")}</h1>
    </section>
    <SearchVerification key={profile.id + ":" + profile.locale} />
    <ContinueShelf />
    <section className="catalog-section"><div className="catalog-section-heading"><h2>{t("Trending today")}</h2></div>
      {loading ? <p className="catalog-status">{t("Loading…")}</p> : null}
      {error ? <p className="banner error-banner" role="alert">{error}</p> : null}
      {!loading && !trending.length ? <p className="empty-state">{t("Nothing here yet")}</p> : null}
      <div className="media-grid">{trending.map(item => <MediaCard key={item.media_type + ":" + item.tmdb_id} item={item} />)}</div>
    </section>
  </main></div>;
}
