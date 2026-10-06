import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import type { ProfileInput } from "../types";
import ProfileWizard from "./ProfileWizard";
import { pendingTasteKey } from "./TasteSelection";
import { useProfile } from "./ProfileContext";
import { translate } from "./i18n";

export default function AddProfilePage() {
  const { setup, pickerLocale, createProfile, profile } = useProfile();
  const [wizardLocale, setWizardLocale] = useState<ProfileInput["locale"]>(profile?.locale ?? pickerLocale ?? setup?.locale ?? "en-US");
  useEffect(() => { document.documentElement.lang = wizardLocale; return () => { document.documentElement.lang = profile?.locale ?? pickerLocale; }; }, [wizardLocale, profile?.locale, pickerLocale]);
  const t = (value: string) => translate(wizardLocale, value);
  const navigate = useNavigate();
  const initial: ProfileInput = {
    name: "", avatar: null, avatar_seed: "", locale: wizardLocale,
    preferred_audio_language: null, preferred_subtitle_language: null,
    subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true,
    onboarding_seeds: [],
  };

  if (profile) return <Navigate to="/" replace />;
  return <div className="product-shell ambient">
    <main className="product-page foundation-page">
      <h1>{t("Add Profile")}</h1>
      <p>{t("New profiles are viewers.")}</p>
      <Link className="back-link" to="/">← {t("Cancel")}</Link>
      <ProfileWizard initial={initial} onLocaleChange={setWizardLocale} onCreate={async values => {
        const created = await createProfile(values);
        localStorage.setItem(pendingTasteKey(created.id), "1");
        navigate(`/profiles/${created.id}/taste`, { replace: true });
      }} />
    </main>
  </div>;
}
