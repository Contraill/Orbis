import { Link } from "react-router-dom";
import { useProfile } from "../app/ProfileContext";
import { GazingProfileAvatar } from "../app/ProfileAvatar";
import { useText } from "../app/i18n";
import { useDirectionalFocus } from "../app/useDirectionalFocus";
import BrandMark from "../app/BrandMark";
import Icon from "../app/Icon";

export default function ProfileSelection() {
  const { profiles, loading, error, selectProfile, reload } = useProfile();
  const t = useText();
  useDirectionalFocus();

  return (
    <main className="product-shell ambient profile-page product-picker">
      <section className="profile-panel">
        <BrandMark className="picker-wordmark" />
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
              <div className="profile-card-wrap" key={item.id}>
                <button className="profile-card" type="button" onClick={() => selectProfile(item.id)}>
                  <span className="profile-avatar"><GazingProfileAvatar seed={item.avatar_seed} config={item.avatar_config} /></span>
                  <strong>{item.name}</strong>
                </button>
              </div>
            ))}
            <Link className="profile-card link-button" to="/profiles/new">
              <span className="profile-avatar"><Icon name="plus" size={40} /></span>
              <strong>{t("Add Profile")}</strong>
            </Link>
          </div>
        ) : null}
      </section>
    </main>
  );
}
