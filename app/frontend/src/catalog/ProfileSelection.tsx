import { Link } from "react-router-dom";
import { useProfile } from "../app/ProfileContext";
import ProfileAvatar from "../app/ProfileAvatar";
import { useText } from "../app/i18n";

export default function ProfileSelection() {
  const { profiles, loading, error, selectProfile, reload } = useProfile();
  const t = useText();

  return (
    <main className="profile-page">
      <section className="profile-panel">
        <p className="eyebrow">ORBIS</p>
        <h1>{t("Who's watching?")}</h1>
        <p className="profile-intro">{t("Choose a profile to keep progress and preferences separate.")}</p>
        {loading ? <div className="catalog-status">{t("Loading…")}</div> : null}
        {error ? (
          <div className="banner error-banner" role="alert">
            {error}
            <button className="inline-action" type="button" onClick={() => void reload()}>{t("Try again")}</button>
          </div>
        ) : null}
        {!loading && !error ? (
          <div className="profile-grid">
            {profiles.map(item => (
              <button className="profile-card" key={item.id} type="button" onClick={() => selectProfile(item.id)}>
                <span className="profile-avatar"><ProfileAvatar seed={item.avatar_seed} /></span>
                <strong>{item.name}</strong>
              </button>
            ))}
            <Link className="profile-card link-button" to="/profiles/new">
              <span className="profile-avatar" aria-hidden="true">+</span>
              <strong>{t("Add Profile")}</strong>
            </Link>
          </div>
        ) : null}
      </section>
    </main>
  );
}
