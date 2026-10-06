import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { deleteOwnProfile, editProfile } from "../api";
import AppHeader from "./AppHeader";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";
import ProfileEditor from "./ProfileEditor";
import ProfileSelection from "../catalog/ProfileSelection";
import { invalidateFeedCache } from "../catalog/InfiniteShelfFeed";

export default function ProfileSettings() {
  const { profile, reload, admin, clearProfile } = useProfile();
  const t = useText();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  if (!profile) return <ProfileSelection />;
  const { id, is_owner: _role, ...preferences } = profile;

  async function confirmDelete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || profile.is_owner || deleting || confirmName !== profile.name) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteOwnProfile(profile.id, confirmName);
      invalidateFeedCache(profile.id);
      clearProfile();
      navigate("/", { replace: true });
      void reload();
    } catch {
      setDeleteError(t("Profile could not be deleted. Try again."));
    } finally {
      setDeleting(false);
    }
  }

  return <div className="product-shell ambient"><AppHeader />
    <main className="product-page foundation-page">
      <div className="catalog-section-heading">
        <h1>{t("Profile settings")}</h1>
      </div>
      <ProfileEditor key={id} initial={preferences} onSave={async values => {
        await editProfile(id, values);
        invalidateFeedCache(id);
        await reload();
      }} />
      {!profile.is_owner ? <section className="profile-delete-section" aria-labelledby="profile-delete-title">
        <h2 id="profile-delete-title">{t("Delete profile")}</h2>
        <p>{t("Deleting this profile also removes its viewing history, list and preferences. This cannot be undone.")}</p>
        {!confirming ? <button className="button danger-outline" type="button" onClick={() => setConfirming(true)}>{t("Delete profile")}</button>
          : <form onSubmit={confirmDelete} className="profile-delete-confirm">
            <label htmlFor="profile-delete-name">{t("Type the profile name to confirm deletion")}: <strong>{profile.name}</strong></label>
            <input id="profile-delete-name" autoComplete="off" value={confirmName} onChange={event => setConfirmName(event.target.value)} disabled={deleting} aria-describedby="profile-delete-help" />
            <p id="profile-delete-help">{t("The name must match exactly.")}</p>
            <div className="profile-delete-actions">
              <button className="button secondary" type="button" disabled={deleting} onClick={() => { setConfirming(false); setConfirmName(""); setDeleteError(""); }}>{t("Cancel")}</button>
              <button className="button danger" type="submit" disabled={deleting || confirmName !== profile.name}>{deleting ? t("Deleting…") : t("Delete profile permanently")}</button>
            </div>
            {deleteError ? <p className="profile-delete-error" role="alert">{deleteError}</p> : null}
          </form>}
      </section> : null}
      {profile.is_owner && admin
        ? <button className="button secondary" onClick={clearProfile}>{t("Sign out")}</button>
        : null}
      <aside className="profile-data-credit" aria-label={t("Credits and data sources")}>
        <h2>{t("Credits and data sources")}</h2>
        <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer" aria-label="TMDB"><img src="/attribution/tmdb.svg" alt="TMDB" /></a>
        <p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
        <p>{t("IMDb ratings, when available, are attributed to IMDb.")}</p>
      </aside>
    </main>
  </div>;
}
