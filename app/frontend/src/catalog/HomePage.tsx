import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";
import SearchVerification from "./SearchVerification";
import FeedVerification from "./FeedVerification";
import type { FeedSurface } from "../api";

export default function HomePage({ surface = "home" }: { surface?: FeedSurface }) {
  const { profile } = useProfile(); const t = useText();
  if (!profile) return <ProfileSelection />;
  return <div className="catalog-shell"><AppHeader /><main className="catalog-main">
    <section className="catalog-hero"><p className="eyebrow">ORBIS · {profile.name}</p><h1>{surface === "home" ? "Home" : t(surface === "movies" ? "Movies" : "Series")}</h1></section>
    <FeedVerification key={`${profile.id}:${profile.locale}:${surface}`} surface={surface} />
    <details><summary>Search and catalog verification</summary><SearchVerification key={profile.id + ":" + profile.locale} /></details>
  </main></div>;
}
