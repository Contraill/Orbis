import { useState, type FormEvent } from "react";
import type { ProfileInput } from "../types";
import ProfileAvatar from "./ProfileAvatar";
import AvatarCustomizer from "./AvatarCustomizer";
import { useText } from "./i18n";

export function newAvatarSeed() { return Array.from(crypto.getRandomValues(new Uint32Array(4))).join("-"); }

// Initial taste seeds are retained in the PATCH payload but are not an editable preference.
export default function ProfileEditor({ initial, onSave }: { initial: ProfileInput; onSave: (values: ProfileInput) => Promise<void> }) {
  const t = useText();
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim() || busy) return;
    setBusy(true); setMessage("");
    try { await onSave({ ...form, name: form.name.trim() }); setMessage(t("Saved")); }
    catch { setMessage(t("Request failed")); }
    finally { setBusy(false); }
  }
  return <form className="foundation-form panel" onSubmit={save}>
    <label>{t("Profile name")}<input required maxLength={80} value={form.name} disabled={busy} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
    <AvatarCustomizer seed={form.avatar_seed} config={form.avatar_config} locale={form.locale} onChange={avatar_config => setForm({ ...form, avatar_config })} onRandomize={() => setForm({ ...form, avatar_seed: newAvatarSeed() })} disabled={busy} />
    <label>{t("Interface language")}<select value={form.locale} disabled={busy} onChange={event => setForm({ ...form, locale: event.target.value as ProfileInput["locale"] })}><option value="en-US">English</option><option value="tr-TR">Türkçe</option></select></label>
    {(["preferred_audio_language", "preferred_subtitle_language"] as const).map((field, index) => <label key={field}>{t(index ? "Subtitle language" : "Audio language")}<select value={form[field] ?? ""} disabled={busy} onChange={event => setForm({ ...form, [field]: event.target.value || null })}><option value="">{t("Provider default")}</option><option value="en">English</option><option value="tr">Türkçe</option></select></label>)}
    {([ ["subtitles_enabled", "Subtitles enabled"], ["autoplay_next_episode", "Autoplay next episode"], ["trailer_muted", "Mute trailers"] ] as const).map(([field, label]) => <label className="checkbox-row" key={field}><input type="checkbox" checked={form[field]} disabled={busy} onChange={event => setForm({ ...form, [field]: event.target.checked })} />{t(label)}</label>)}
    <button className="button primary" disabled={busy || !form.name.trim()}>{t("Save")}</button>
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
