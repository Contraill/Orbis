import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import ProfileSelection from "./ProfileSelection";
import InfiniteShelfFeed from "./InfiniteShelfFeed";
import type { FeedSurface } from "../api";

export default function HomePage({ surface = "home" }: { surface?: FeedSurface }) {
  const { profile } = useProfile(); const t = useText();
  if (!profile) return <ProfileSelection />;
  return <div className="product-shell ambient subtle"><AppHeader /><main id="main-content" className="browse-main" key={`${profile.id}:${profile.locale}:${surface}`}>
    <InfiniteShelfFeed profileId={profile.id} locale={profile.locale} surface={surface} fallbackTitle={t(surface === "home" ? "Your next story starts here" : surface === "movies" ? "Discover films" : "Discover series")} />
  </main></div>;
}
