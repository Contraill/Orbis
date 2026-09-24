import {
  useEffect,
  useRef,
  useState,
} from "react";

import {
  Link,
  useParams,
} from "react-router-dom";

import {
  activateProviderDraft,
  getLiveProvider,
  getProviderSettings,
  rollbackProvider,
  saveProviderDraft,
  saveProviderSettings,
  validateProviderDraft,
  revertToFactory,
  type ProviderSettingsView,
} from "../api";

import type {
  LiveProviderState,
  ProviderValidation,
} from "../types";


type EditorTab =
  | "general"
  | "code"
  | "settings"
  | "versions";


export default function ProviderEditorPage() {
  const { providerId = "" } = useParams();

  const [provider, setProvider] =
    useState<LiveProviderState | null>(null);

  const [tab, setTab] =
    useState<EditorTab>("general");

  const [code, setCode] = useState("");

  const [settings, setSettings] = useState<ProviderSettingsView | null>(null);
  const [changes, setChanges] = useState<Record<string, unknown>>({});
  const settingsVersion = useRef<LiveProviderState | null>(null);

  const [validation, setValidation] =
    useState<ProviderValidation | null>(null);

  const [message, setMessage] =
    useState<string | null>(null);

  const [error, setError] =
    useState<string | null>(null);

  const [busy, setBusy] = useState(false);


  useEffect(() => {
    let cancelled = false;

    setProvider(null);
    setValidation(null);
    setMessage(null);
    setError(null);

    Promise.all([
      getLiveProvider(providerId),
      getProviderSettings(providerId),
    ])
      .then(([state, settings]) => {
        if (cancelled) {
          return;
        }

        setProvider(state);
        setCode(state.draft_code);
        setSettings(settings);
        setChanges({});
        settingsVersion.current = state;
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Provider load failed",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [providerId]);


  useEffect(() => {
    let cancelled = false;
    const previous = settingsVersion.current;
    if (!provider || (previous?.provider_id === provider.provider_id
      && previous.active_code === provider.active_code
      && previous.implementation === provider.implementation)) return;
    settingsVersion.current = provider;
    if (provider) getProviderSettings(providerId).then(value => {
      if (!cancelled) { setSettings(value); setChanges({}); }
    }).catch(reason => { if (!cancelled) setError(String(reason)); });
    return () => { cancelled = true; };
  }, [providerId, provider?.active_code, provider?.implementation]);

  async function saveDraft() {
    setBusy(true);
    setError(null);
    setMessage(null);

    try {
      const state = await saveProviderDraft(
        providerId,
        code,
      );

      setProvider(state);
      setMessage("Draft saved.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Save failed",
      );
    } finally {
      setBusy(false);
    }
  }


  async function validate() {
    setBusy(true);
    setError(null);
    setMessage(null);

    try {
      await saveProviderDraft(
        providerId,
        code,
      );

      const result =
        await validateProviderDraft(
          providerId,
        );

      setValidation(result);

      setMessage(
        result.valid
          ? "Validation passed."
          : "Validation failed.",
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Validation failed",
      );
    } finally {
      setBusy(false);
    }
  }


  async function activate() {
    setBusy(true);
    setError(null);
    setMessage(null);

    try {
      await saveProviderDraft(
        providerId,
        code,
      );

      const state =
        await activateProviderDraft(
          providerId,
        );

      setProvider(state);
      setCode(state.draft_code);
      setMessage(
        "Activated without restarting Docker.",
      );

      const result =
        await validateProviderDraft(
          providerId,
        );

      setValidation(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Activation failed",
      );
    } finally {
      setBusy(false);
    }
  }


  async function saveSettings() {
    setBusy(true);
    setError(null);
    setMessage(null);

    try {
      const updated = await saveProviderSettings(providerId, changes);
      setSettings(updated);
      setChanges({});

      setMessage("Settings saved.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Settings failed",
      );
    } finally {
      setBusy(false);
    }
  }


  async function rollback(version: string) {
    if (
      !window.confirm(
        `Rollback ${providerId} to ${version}?`,
      )
    ) {
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    setValidation(null);

    try {
      const state = await rollbackProvider(
        providerId,
        version,
      );

      setProvider(state);
      setCode(state.draft_code);
      setMessage("Rollback activated.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Rollback failed",
      );
    } finally {
      setBusy(false);
    }
  }


  if (!provider) {
    return (
      <section className="admin-page">
        {error ?? "Loading provider…"}
      </section>
    );
  }


  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <Link
            className="back-link"
            to="/admin/providers"
          >
            ← Providers
          </Link>

          <p className="section-kicker">
            LIVE PROVIDER
          </p>

          <h2>{provider.name}</h2>

          <code>{provider.provider_id}</code>
        </div>

        <span
          className={
            provider.loaded
              ? "status healthy"
              : "status unknown"
          }
        >
          {provider.loaded
            ? "LOADED"
            : "DRAFT"}
        </span>
      </div>

      {provider.is_factory_override && (
        <div className="panel">
          <p>Factory override · Active implementation: {provider.implementation === "live" ? "Override" : "Factory"}</p>
          <button className="button secondary" disabled={busy || provider.implementation !== "live"}
            onClick={async () => {
              if (!window.confirm("Restore the factory provider? Your draft and versions will be kept.")) return;
              setBusy(true);
              setError(null);
              try {
                setProvider(await revertToFactory(providerId));
                setMessage("Factory provider restored. Draft and versions retained.");
              } catch (err) {
                setError(err instanceof Error ? err.message : "Revert failed");
              } finally { setBusy(false); }
            }}>
            Revert to Factory
          </button>
        </div>
      )}

      <nav className="provider-editor-tabs">
        {(
          [
            "general",
            "code",
            "settings",
            "versions",
          ] as EditorTab[]
        ).map((name) => (
          <button
            key={name}
            className={
              tab === name
                ? "editor-tab active"
                : "editor-tab"
            }
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>

      {error && (
        <div className="banner error-banner">
          {error}
        </div>
      )}

      {message && (
        <div className="banner success-banner">
          {message}
        </div>
      )}

      {tab === "general" && (
        <article className="panel">
          <dl className="provider-stats">
            <div>
              <dt>Loaded</dt>
              <dd>
                {provider.loaded ? "Yes" : "No"}
              </dd>
            </div>

            <div>
              <dt>Active version</dt>
              <dd>
                {provider.has_active
                  ? "Yes"
                  : "No"}
              </dd>
            </div>

            <div>
              <dt>Saved versions</dt>
              <dd>
                {provider.versions.length}
              </dd>
            </div>

            <div>
              <dt>Runtime path</dt>
              <dd>
                /config/providers/{provider.provider_id}
              </dd>
            </div>
          </dl>

          <p className="muted">
            Draft changes do not affect playback
            until Activate succeeds.
          </p>
        </article>
      )}

      {tab === "code" && (
        <article className="panel code-panel">
          <div className="code-toolbar">
            <div>
              <p className="section-kicker">
                DRAFT.PY
              </p>

              <span className="muted">
                Validate before activation
              </span>
            </div>

            <div className="provider-actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void saveDraft()
                }
              >
                Save Draft
              </button>

              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void validate()
                }
              >
                Validate
              </button>

              <button
                className="button primary"
                disabled={busy}
                onClick={() =>
                  void activate()
                }
              >
                Activate
              </button>
            </div>
          </div>

          <textarea
            className="code-editor"
            value={code}
            spellCheck={false}
            onChange={(event) => {
              setCode(event.target.value);
              setValidation(null);
              setMessage(null);
            }}
          />

          {validation && (
            <div
              className={
                validation.valid
                  ? "validation-box valid"
                  : "validation-box invalid"
              }
            >
              <strong>
                {validation.valid
                  ? "Validation passed"
                  : "Validation failed"}
              </strong>

              {validation.errors.map(
                (item) => (
                  <code key={item}>
                    {item}
                  </code>
                ),
              )}
            </div>
          )}
        </article>
      )}

      {tab === "settings" && (
        <article className="panel">
          <p className="section-kicker">
            SETTINGS.JSON
          </p>

          <p className="muted">
            Runtime provider configuration.
            This file is outside Git.
          </p>

          {!settings?.schema_available ? <p>Validate and activate this provider to load its settings schema.</p>
            : settings.schema.length === 0 ? <p>No configurable settings.</p>
            : <>
              {settings.schema.map(field => {
                const value = field.key in changes ? changes[field.key] : settings.values[field.key];
                const change = (next: unknown) => setChanges(old => ({ ...old, [field.key]: next }));
                return <div key={field.key} className="form-field">
                  <label htmlFor={`setting-${field.key}`}>{field.label}{field.required ? " *" : ""}</label>
                  {field.sensitive ? <>
                    <input id={`setting-${field.key}`} type="password" autoComplete="new-password"
                      disabled={busy} maxLength={field.max_length} value={String(changes[field.key] ?? "")}
                      placeholder={settings.configured_secrets.includes(field.key) ? "Configured — leave unchanged" : "Not configured"}
                      onChange={event => change(event.target.value)} />
                    <button disabled={busy} onClick={() => change(null)}>Clear {field.label}</button>
                    {changes[field.key] === null ? <small>Will be cleared on save.</small> : null}
                  </> : field.type === "boolean" ? <input id={`setting-${field.key}`} type="checkbox" disabled={busy}
                    checked={Boolean(value)} onChange={event => change(event.target.checked)} />
                    : field.type === "enum" ? <select id={`setting-${field.key}`} disabled={busy} value={String(value ?? "")}
                      onChange={event => change(event.target.value)}>
                        <option value="" disabled>Select</option>
                        {field.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
                      </select>
                    : <input id={`setting-${field.key}`} disabled={busy} required={field.required}
                        type={field.type === "integer" ? "number" : field.type === "url" ? "url" : "text"}
                        min={field.minimum ?? undefined} max={field.maximum ?? undefined} maxLength={field.max_length}
                        value={String(value ?? "")} onChange={event => change(field.type === "integer"
                          ? event.target.value === "" ? null : Number(event.target.value) : event.target.value)} />}
                  <p className="muted">{field.description}</p>
                </div>;
              })}
              <button className="button primary" disabled={busy} onClick={() => void saveSettings()}>Save settings</button>
            </>}
        </article>
      )}

      {tab === "versions" && (
        <article className="panel">
          <p className="section-kicker">
            ROLLBACK
          </p>

          {provider.versions.length === 0 ? (
            <p className="muted">
              No previous active versions yet.
            </p>
          ) : (
            <div className="version-list">
              {provider.versions.map(
                (version) => (
                  <div
                    className="version-row"
                    key={version}
                  >
                    <code>{version}</code>

                    <button
                      className="button secondary compact"
                      disabled={busy}
                      onClick={() =>
                        void rollback(version)
                      }
                    >
                      Rollback
                    </button>
                  </div>
                ),
              )}
            </div>
          )}
        </article>
      )}
    </section>
  );
}
