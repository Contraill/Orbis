import { useEffect, useState, type ReactNode } from "react";
import { bootstrapOwner, editProfile, setSetupLocale } from "../api";
import type { Profile, ProfileInput } from "../types";
import { useProfile } from "./ProfileContext";
import { useText, translate } from "./i18n";
import { useDirectionalFocus } from "./useDirectionalFocus";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import ProfileWizard from "./ProfileWizard";
import { pendingTasteKey } from "./TasteSelection";

export default function SetupGate({ children }: { children: ReactNode }) {
  const { setup, loading, error, reload, authenticate, profile } = useProfile();
  const t = useText();
  const navigate = useNavigate();
  const location = useLocation();
  useDirectionalFocus(Boolean(setup?.setup_required));
  const [locale, setLocale] = useState<Profile["locale"]>("en-US");
  const [step, setStep] = useState(0);
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (setup?.setup_required) document.documentElement.lang = locale; }, [setup?.setup_required, locale]);
  if (!setup && loading) return <main className="product-shell ambient product-loading">{t("Loading…")}</main>;
  if (!setup || error) return <main className="product-shell ambient product-state"><p role="alert">{error}</p><button className="orbis-button" onClick={() => void reload()}>{t("Try again")}</button></main>;
  if (!setup.setup_required) {
    if (profile && localStorage.getItem(pendingTasteKey(profile.id)) === "1" && location.pathname !== `/profiles/${profile.id}/taste`) return <Navigate to={`/profiles/${profile.id}/taste`} replace />;
    return <div key={`${profile?.id ?? "none"}:${profile?.locale ?? setup.locale}`}>{children}</div>;
  }
  const initial: ProfileInput = { name: "", avatar: null, avatar_seed: "", locale,
    preferred_audio_language: null, preferred_subtitle_language: null,
    subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true, onboarding_seeds: [] };
  async function next() {
    setBusy(true); setFailure("");
    try { await setSetupLocale(locale); await reload(); setStep(1); }
    catch (reason) { setFailure(String(reason)); }
    finally { setBusy(false); }
  }
  async function create(values: ProfileInput) {
    if (password.length < 12) { setFailure(translate(locale, "Use at least 12 characters")); return; }
    setBusy(true); setFailure("");
    try {
      const result = await bootstrapOwner(values.name, password, locale);
      sessionStorage.setItem("orbis.owner-session", result.token);
      await editProfile(result.owner_id, values);
      setPassword("");
      await authenticate(result.token);
      localStorage.setItem(pendingTasteKey(result.owner_id), "1");
      navigate(`/profiles/${result.owner_id}/taste`, { replace: true });
      window.scrollTo(0, 0);
    } catch (reason) { setFailure(String(reason)); throw reason; }
    finally { setBusy(false); }
  }
  return <main className="product-shell ambient setup-page"><div className="setup-orbit" aria-hidden="true" /><div className="setup-inner">
    <img className="setup-brand" src="/brand/wordmark.png" alt="Orbis" />
    <span className="orbis-kicker">{step === 0 ? "01 / 02" : "02 / 02"}</span>
    {step === 0 ? <section className="setup-intro"><h1>{translate(locale, "Welcome to Orbis")}</h1><p>{translate(locale, "A place for every story.")}</p>
      <h2>{translate(locale, "Choose your language")}</h2>
      <div className="language-picks"><button className={locale === "en-US" ? "selected" : ""} onClick={() => setLocale("en-US")}>English <span>↗</span></button><button className={locale === "tr-TR" ? "selected" : ""} onClick={() => setLocale("tr-TR")}>Türkçe <span>↗</span></button></div>
      <button className="orbis-button accent" disabled={busy} onClick={() => void next()}>{translate(locale, "Continue")} →</button>
    </section> : <section className="setup-profile"><h1>{translate(locale, "Create your profile")}</h1><p>{translate(locale, "Make Orbis your own")}</p>
      <ProfileWizard initial={initial} onLocaleChange={setLocale} canCreate={password.length >= 12} onCreate={create} extraFinal={<label className="setup-password">{translate(locale, "Password")}<input type="password" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /><small>{translate(locale, "Use at least 12 characters")}</small></label>} />
    </section>}
    {failure ? <p role="alert" className="form-error">{failure}</p> : null}
  </div></main>;
}
