import { Link } from "react-router-dom";
import { editProfile } from "../api";
import AppHeader from "./AppHeader";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";
import ProfileEditor from "./ProfileEditor";
import ProfileSelection from "../catalog/ProfileSelection";

export default function ProfileSettings() {
  const { profile, reload, admin, clearProfile } = useProfile();
  const t = useText();
  if (!profile) return <ProfileSelection />;
  const { id, is_owner: _role, ...preferences } = profile;

  return <div className="catalog-shell"><AppHeader />
    <main className="catalog-main foundation-page">
      <div className="catalog-section-heading">
        <h1>{t("Profile preferences")}</h1>
        <Link className="button primary link-button" to="/profiles/new">+ {t("Add Profile")}</Link>
      </div>
      <ProfileEditor key={id} initial={preferences} onSave={async values => {
        await editProfile(id, values);
        await reload();
      }} />
      {profile.is_owner && admin
        ? <button className="button secondary" onClick={clearProfile}>{t("Sign out")}</button>
        : null}
    </main>
  </div>;
}
