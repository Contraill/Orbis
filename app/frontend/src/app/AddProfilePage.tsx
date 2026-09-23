import { Link, useNavigate } from "react-router-dom";
import type { ProfileInput } from "../types";
import AppHeader from "./AppHeader";
import ProfileEditor from "./ProfileEditor";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";

export default function AddProfilePage() {
  const { setup, createProfile } = useProfile();
  const t = useText();
  const navigate = useNavigate();
  const initial: ProfileInput = {
    name: "", avatar: null, avatar_seed: "", locale: setup?.locale ?? "en-US",
    preferred_audio_language: null, preferred_subtitle_language: null,
    subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true,
    onboarding_seeds: [],
  };

  return <div className="catalog-shell"><AppHeader />
    <main className="catalog-main foundation-page">
      <h1>{t("Add Profile")}</h1>
      <p>{t("New profiles are viewers.")}</p>
      <Link className="back-link" to="/profile">← {t("Cancel")}</Link>
      <ProfileEditor initial={initial} creating onSave={async values => {
        await createProfile(values);
        navigate("/profile", { replace: true });
      }} />
    </main>
  </div>;
}
