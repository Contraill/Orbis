import { Link } from "react-router-dom";

import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";
import ProfileAvatar from "./ProfileAvatar";


export default function AppHeader() {
  const { profile, clearProfile } = useProfile();
  const t = useText();

  return (
    <header className="app-header">
      <Link className="app-brand" to="/">
        <span className="app-brand-mark">O</span>
        <span>Orbis</span>
      </Link>

      <nav className="app-nav" aria-label="Main navigation">
        <Link to="/">{t("Browse")}</Link>
        <Link to="/movies">{t("Movies")}</Link>
        <Link to="/series">{t("Series")}</Link>
        <Link to="/library">{t("Library")}</Link>
        <Link to="/profile">{t("Profile")}</Link>
        {profile?.is_owner ? <Link to="/admin">{t("Admin")}</Link> : null}
        {profile ? (
          <button
            className="profile-chip"
            type="button"
            onClick={clearProfile}
            aria-label={`Switch profile. Current profile: ${profile.name}`}
          >
            <ProfileAvatar seed={profile.avatar_seed} size={32} />
            {profile.name}
          </button>
        ) : null}
      </nav>
    </header>
  );
}
