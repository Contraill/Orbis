import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { ProfileInput } from "../types";
import ProfileAvatar from "./ProfileAvatar";
import AvatarCustomizer from "./AvatarCustomizer";
import { newAvatarSeed } from "./ProfileEditor";
import { translate } from "./i18n";

const headings = ["What's your name?", "Choose your avatar", "Choose your language", "Playback languages", "Playback behavior", "Ready to create your profile?"];

export default function ProfileWizard({ initial, onCreate, extraFinal, canCreate = true, onLocaleChange }: { initial: ProfileInput; onCreate: (values: ProfileInput) => Promise<void>; extraFinal?: ReactNode; canCreate?: boolean; onLocaleChange?: (locale: ProfileInput["locale"]) => void }) {
  const [form, setForm] = useState<ProfileInput>(() => ({ ...initial, avatar_seed: initial.avatar_seed || newAvatarSeed() }));
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (step > 0) heading.current?.focus(); }, [step]);
  const t = (value: string) => translate(form.locale, value);
  function next(event: FormEvent) {
    event.preventDefault();
    if (step === 0 && !form.name.trim()) { setError(t("Enter a profile name.")); return; }
    setError("");
    if (step < headings.length - 1) { setStep(step + 1); return; }
    if (!canCreate || busy) return;
    setBusy(true);
    void onCreate({ ...form, name: form.name.trim(), onboarding_seeds: [] }).catch(() => setError(t("Profile could not be created. Try again."))).finally(() => setBusy(false));
  }
  return <section className="profile-wizard panel" aria-label={t("Create your profile")}>
    <p className="wizard-progress" aria-live="polite">{t("Step")} {step + 1} / {headings.length}<span aria-hidden="true"><i style={{ width: `${(step + 1) / headings.length * 100}%` }} /></span></p>
    <form onSubmit={next}>
      <h2 ref={heading} tabIndex={-1}>{t(headings[step])}</h2>
      {step === 0 ? <label>{t("Profile name")}<input autoFocus required maxLength={80} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label> : null}
      {step === 1 ? <AvatarCustomizer seed={form.avatar_seed} config={form.avatar_config} locale={form.locale} onChange={avatar_config => setForm({ ...form, avatar_config })} onRandomize={() => setForm({ ...form, avatar_seed: newAvatarSeed() })} /> : null}
      {step === 2 ? <div className="language-picks wizard-languages"><button type="button" className={form.locale === "en-US" ? "selected" : ""} aria-pressed={form.locale === "en-US"} onClick={() => { setForm({ ...form, locale: "en-US" }); onLocaleChange?.("en-US"); }}>English</button><button type="button" className={form.locale === "tr-TR" ? "selected" : ""} aria-pressed={form.locale === "tr-TR"} onClick={() => { setForm({ ...form, locale: "tr-TR" }); onLocaleChange?.("tr-TR"); }}>Türkçe</button></div> : null}
      {step === 3 ? <div className="wizard-fields">{(["preferred_audio_language", "preferred_subtitle_language"] as const).map((field, index) => <label key={field}>{t(index ? "Subtitle language" : "Audio language")}<select value={form[field] ?? ""} onChange={event => setForm({ ...form, [field]: event.target.value || null })}><option value="">{t("Provider default")}</option><option value="en">English</option><option value="tr">Türkçe</option></select></label>)}<label className="checkbox-row"><input type="checkbox" checked={form.subtitles_enabled} onChange={event => setForm({ ...form, subtitles_enabled: event.target.checked })} />{t("Subtitles enabled")}</label></div> : null}
      {step === 4 ? <div className="wizard-fields"><label className="checkbox-row"><input type="checkbox" checked={form.autoplay_next_episode} onChange={event => setForm({ ...form, autoplay_next_episode: event.target.checked })} />{t("Autoplay next episode")}</label><label className="checkbox-row"><input type="checkbox" checked={form.trailer_muted} onChange={event => setForm({ ...form, trailer_muted: event.target.checked })} />{t("Mute trailers")}</label></div> : null}
      {step === 5 ? <div className="wizard-review"><ProfileAvatar seed={form.avatar_seed} config={form.avatar_config} size={92} prominent /><strong>{form.name.trim()}</strong><span>{form.locale === "tr-TR" ? "Türkçe" : "English"}</span>{extraFinal}</div> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="wizard-actions">{step > 0 ? <button type="button" className="button secondary" disabled={busy} onClick={() => { setError(""); setStep(step - 1); }}>{t("Back")}</button> : null}<button className="button primary" disabled={busy || (step === 0 && !form.name.trim()) || (step === 5 && !canCreate)}>{t(step === 5 ? busy ? "Creating…" : "Create Profile" : "Continue")}</button></div>
    </form>
  </section>;
}
