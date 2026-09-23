import { useState, type ReactNode, type FormEvent } from "react";
import { bootstrapOwner, setSetupLocale } from "../api";
import type { Profile } from "../types";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";

export default function SetupGate({ children }: { children: ReactNode }) {
  const { setup, loading, error, reload, authenticate, profile } = useProfile();
  const t = useText();
  const [locale, setLocale] = useState<Profile["locale"]>("en-US");
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setFailure("");
    try {
      if (step === 0) { await setSetupLocale(locale); await reload(); setStep(1); }
      else { const result = await bootstrapOwner(name, password); setPassword(""); await authenticate(result.token); }
    } catch (reason) { setFailure(reason instanceof Error ? reason.message : "Request failed"); }
    finally { setBusy(false); }
  }
  if (!setup && loading) return <main className="profile-page">Loading…</main>;
  if (!setup || error) return <main className="profile-page"><p role="alert">{error}</p><button onClick={() => void reload()}>{t("Try again")}</button></main>;
  if (!setup.setup_required) return <div key={`${profile?.id ?? "none"}:${profile?.locale ?? setup.locale}`}>{children}</div>;
  return <main className="profile-page"><section className="profile-panel">
    <h1>{step === 0 ? "Welcome to Orbis" : t("Create installation owner")}</h1>
    <form className="foundation-form" onSubmit={submit}>
      {step === 0 ? <label>Interface language<select value={locale} onChange={e => setLocale(e.target.value as Profile["locale"])}><option value="en-US">English</option><option value="tr-TR">Türkçe</option></select></label> : <>
        <label>{t("Profile name")}<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>{t("Password")}<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <small>{t("Use at least 12 characters")}</small>
      </>}
      {failure ? <p role="alert">{t(failure)}</p> : null}
      <button className="button primary" disabled={busy}>{t(step === 0 ? "Continue" : "Create")}</button>
    </form>
  </section></main>;
}
