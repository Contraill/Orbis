import {
  useState,
  type FormEvent,
} from "react";

import { useProfile } from "../app/ProfileContext";


export default function ProfileSelection() {
  const {
    profiles,
    loading,
    error,
    selectProfile,
    createProfile,
    reload,
  } = useProfile();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] =
    useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextName = name.trim();
    if (!nextName || creating) return;

    setCreating(true);
    setCreateError(null);
    try {
      await createProfile(nextName);
      setName("");
    } catch (reason) {
      setCreateError(
        reason instanceof Error
          ? reason.message
          : "Profile could not be created",
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="profile-page">
      <section className="profile-panel">
        <p className="eyebrow">MEDIA APP</p>
        <h1>Who’s watching?</h1>
        <p className="profile-intro">
          Choose a profile to keep progress and preferences separate.
        </p>

        {loading ? (
          <div className="catalog-status">Loading profiles…</div>
        ) : null}

        {error ? (
          <div className="banner error-banner">
            {error}
            <button
              className="inline-action"
              type="button"
              onClick={() => void reload()}
            >
              Try again
            </button>
          </div>
        ) : null}

        {!loading && !error ? (
          <div className="profile-grid">
            {profiles.map((item) => (
              <button
                className="profile-card"
                key={item.id}
                type="button"
                onClick={() => selectProfile(item.id)}
              >
                <span className="profile-avatar">
                  {item.name.slice(0, 1).toUpperCase()}
                </span>
                <strong>{item.name}</strong>
              </button>
            ))}
          </div>
        ) : null}

        {!loading && !error && profiles.length === 0 ? (
          <p className="empty-state">
            No profiles yet. Create one to start watching.
          </p>
        ) : null}

        <form className="profile-create" onSubmit={submit}>
          <label htmlFor="profile-name">New profile</label>
          <div>
            <input
              id="profile-name"
              value={name}
              maxLength={80}
              placeholder="Profile name"
              onChange={(event) => setName(event.target.value)}
            />
            <button
              className="button primary"
              type="submit"
              disabled={!name.trim() || creating}
            >
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
          {createError ? (
            <p className="form-error">{createError}</p>
          ) : null}
        </form>

        <a className="admin-link" href="/admin">
          Administration →
        </a>
      </section>
    </main>
  );
}
