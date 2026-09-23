import { useState, type FormEvent } from "react";
import { searchCatalog } from "../api";
import type { CatalogItem, ProfileInput } from "../types";
import ProfileAvatar from "./ProfileAvatar";
import { useText } from "./i18n";

interface Props {
  initial: ProfileInput;
  onSave: (values: ProfileInput) => Promise<void>;
  creating?: boolean;
}

// One set of onboarding/preferences fields for both creation and editing.
export default function ProfileEditor({ initial, onSave, creating = false }: Props) {
  const t = useText();
  const [form, setForm] = useState(initial);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CatalogItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [message, setMessage] = useState("");
  const avatarSeed = form.avatar_seed || form.name.trim();

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !form.name.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      await onSave({ ...form, name: form.name.trim(), avatar_seed: avatarSeed });
      if (!creating) setMessage("Saved");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Request failed");
    } finally { setBusy(false); }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (searching || !query.trim()) return;
    setSearching(true);
    setMessage("");
    try {
      setResults((await searchCatalog(query.trim())).results);
      setSearched(true);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Request failed");
    } finally { setSearching(false); }
  }

  return <>
    <form className="foundation-form panel" onSubmit={save}>
      <ProfileAvatar seed={avatarSeed || "Orbis"} />
      <label>{t("Profile name")}
        <input required maxLength={80} disabled={busy} value={form.name}
          onChange={e => setForm({ ...form, name: e.target.value })} />
      </label>
      <label>{t("Avatar seed")}
        <input maxLength={255} disabled={busy} value={avatarSeed}
          placeholder={t("Defaults to the profile name")}
          onChange={e => setForm({ ...form, avatar_seed: e.target.value })} />
      </label>
      <button type="button" className="button secondary" disabled={busy} onClick={() => setForm({
        ...form, avatar_seed: Array.from(crypto.getRandomValues(new Uint32Array(4))).join("-"),
      })}>{t("New avatar")}</button>
      <label>{t("Interface language")}
        <select value={form.locale} disabled={busy}
          onChange={e => setForm({ ...form, locale: e.target.value as ProfileInput["locale"] })}>
          <option value="en-US">English</option><option value="tr-TR">Türkçe</option>
        </select>
      </label>
      {(["preferred_audio_language", "preferred_subtitle_language"] as const).map((field, index) => (
        <label key={field}>{t(index === 0 ? "Audio language" : "Subtitle language")}
          <select value={form[field] ?? ""} disabled={busy}
            onChange={e => setForm({ ...form, [field]: e.target.value || null })}>
            <option value="">{t("Provider default")}</option>
            <option value="en">English</option><option value="tr">Türkçe</option>
            {form[field] && !["en", "tr"].includes(form[field]) ? <option value={form[field]}>{form[field]}</option> : null}
          </select>
        </label>
      ))}
      {([
        ["subtitles_enabled", "Subtitles enabled"],
        ["autoplay_next_episode", "Autoplay next episode"],
        ["trailer_muted", "Mute trailers"],
      ] as const).map(([field, label]) => (
        <label className="checkbox-row" key={field}>
          <input type="checkbox" checked={form[field]} disabled={busy}
            onChange={e => setForm({ ...form, [field]: e.target.checked })} />{t(label)}
        </label>
      ))}
      <p>{t("Selected")}: {form.onboarding_seeds.length}/5</p>
      <div className="foundation-actions">{form.onboarding_seeds.map(seed => (
        <button className="button secondary" type="button" disabled={busy}
          key={`${seed.media_type}:${seed.tmdb_id}`}
          onClick={() => setForm({ ...form, onboarding_seeds: form.onboarding_seeds.filter(s => s !== seed) })}>
          {results.find(r => r.media_type === seed.media_type && r.tmdb_id === seed.tmdb_id)?.title ?? `${seed.media_type} #${seed.tmdb_id}`} ×
        </button>
      ))}</div>
      <button className="button primary" disabled={busy || searching || !form.name.trim()}>
        {t(creating ? busy ? "Creating…" : "Create" : "Save")}
      </button>
    </form>
    <section className="panel">
      <h2>{t("Choose up to five movies or series")}</h2>
      <form className="foundation-actions" onSubmit={search}>
        <label>{t("Search")}<input type="search" required value={query} disabled={searching || busy}
          onChange={e => setQuery(e.target.value)} /></label>
        <button className="button secondary" disabled={searching || busy}>{t("Search")}</button>
      </form>
      {searching ? <p>{t("Loading…")}</p> : searched && !results.length ? <p>{t("Nothing here yet")}</p> : null}
      <div className="foundation-actions">{results.map(item => {
        const selected = form.onboarding_seeds.some(s => s.media_type === item.media_type && s.tmdb_id === item.tmdb_id);
        return <button className="button secondary" key={`${item.media_type}:${item.tmdb_id}`}
          disabled={busy || selected || form.onboarding_seeds.length >= 5}
          onClick={() => setForm(current => ({ ...current, onboarding_seeds: [
            ...current.onboarding_seeds, { media_type: item.media_type, tmdb_id: item.tmdb_id },
          ] }))}>{item.title} {selected ? "✓" : "+"}</button>;
      })}</div>
    </section>
    {message ? <p role="status">{t(message)}</p> : null}
  </>;
}
