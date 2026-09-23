import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  Link,
  useNavigate,
} from "react-router-dom";

import {
  createLiveProvider,
  createFactoryOverride,
  deleteLiveProvider,
  listLiveProviders,
  listProviders,
  testProvider,
  updateProvider,
} from "../api";

import type {
  LiveProviderState,
  ProviderAdminView,
} from "../types";

import {
  formatDate,
  formatLatency,
  StatusBadge,
} from "./shared";


export default function ProvidersPage() {
  const navigate = useNavigate();

  async function editFactory(providerId: string) {
    setBusy(`override:${providerId}`);
    setError(null);
    try {
      await createFactoryOverride(providerId);
      navigate(`/admin/providers/${providerId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Override creation failed");
    } finally {
      setBusy(null);
    }
  }
  const [providers, setProviders] =
    useState<ProviderAdminView[]>([]);

  const [liveProviders, setLiveProviders] =
    useState<LiveProviderState[]>([]);

  const [priorities, setPriorities] =
    useState<Record<string, string>>({});

  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");

  const [busy, setBusy] =
    useState<string | null>(null);

  const [message, setMessage] =
    useState<string | null>(null);

  const [error, setError] =
    useState<string | null>(null);


  const liveIds = useMemo(
    () => new Set(
      liveProviders.map(
        (provider) => provider.provider_id,
      ),
    ),
    [liveProviders],
  );


  async function refresh() {
    const [providerData, liveData] =
      await Promise.all([
        listProviders(),
        listLiveProviders(),
      ]);

    setProviders(providerData);
    setLiveProviders(liveData);

    setPriorities(
      Object.fromEntries(
        providerData.map((provider) => [
          provider.provider_id,
          String(provider.priority),
        ]),
      ),
    );
  }


  useEffect(() => {
    refresh().catch((err) => {
      setError(
        err instanceof Error
          ? err.message
          : "Providers failed",
      );
    });
  }, []);


  async function createProvider() {
    if (!newId.trim() || !newName.trim()) {
      setError("Provider ID ve name gerekli.");
      return;
    }

    setBusy("create");
    setError(null);

    try {
      await createLiveProvider(
        newId.trim(),
        newName.trim(),
      );

      setNewId("");
      setNewName("");
      setMessage("Draft provider created.");
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Create failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function removeProvider(providerId: string) {
    if (!window.confirm(`Delete ${providerId}? Its live code, settings and versions will be permanently removed. This cannot be undone.`)) return;
    setBusy(`delete:${providerId}`);
    setError(null);
    setMessage(null);
    try {
      await deleteLiveProvider(providerId);
      await refresh();
      setMessage(`${providerId} deleted.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(null);
    }
  }


  async function toggle(provider: ProviderAdminView) {
    setBusy(`toggle:${provider.provider_id}`);

    try {
      await updateProvider(
        provider.provider_id,
        {
          enabled: !provider.enabled,
        },
      );

      await refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Update failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function savePriority(
    provider: ProviderAdminView,
  ) {
    const value = Number(
      priorities[provider.provider_id],
    );

    if (!Number.isInteger(value) || value < 0) {
      setError("Priority geçersiz.");
      return;
    }

    setBusy(`priority:${provider.provider_id}`);

    try {
      await updateProvider(
        provider.provider_id,
        {
          priority: value,
        },
      );

      await refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Update failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function health(provider: ProviderAdminView) {
    setBusy(`health:${provider.provider_id}`);

    try {
      const result = await testProvider(
        provider.provider_id,
      );

      setMessage(
        `${provider.name}: ${
          result.healthy ? "healthy" : "failed"
        } — ${formatLatency(result.latency_ms)}`,
      );

      await refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Health failed",
      );
    } finally {
      setBusy(null);
    }
  }


  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="section-kicker">
            REGISTRY
          </p>

          <h2>Providers</h2>

          <p className="muted">
            Lower priority runs first.
          </p>
        </div>
      </div>

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

      <article className="panel create-provider-panel">
        <div>
          <p className="section-kicker">
            LIVE ADAPTER
          </p>
          <h3>New Provider</h3>
        </div>

        <div className="create-provider-fields">
          <input
            value={newId}
            placeholder="provider-id"
            onChange={(event) =>
              setNewId(event.target.value)
            }
          />

          <input
            value={newName}
            placeholder="Provider name"
            onChange={(event) =>
              setNewName(event.target.value)
            }
          />

          <button
            className="button primary"
            disabled={busy !== null}
            onClick={() => void createProvider()}
          >
            Create draft
          </button>
        </div>
      </article>

      <div className="provider-grid">
        {providers.map((provider) => (
          <article
            className="provider-card"
            key={provider.provider_id}
          >
            <div className="provider-card-head">
              <div>
                <h3>{provider.name}</h3>

                <code>
                  {provider.provider_id}
                </code>
              </div>

              <StatusBadge
                status={provider.status}
              />
            </div>

            <div className="capabilities">
              <span>
                {liveIds.has(provider.provider_id)
                  ? "LIVE"
                  : "BUILT-IN"}
              </span>

              {provider.capabilities.movie && (
                <span>Movie</span>
              )}

              {provider.capabilities.episode && (
                <span>Episode</span>
              )}

              {provider.capabilities.protocols.map(
                (protocol) => (
                  <span key={protocol}>
                    {protocol.toUpperCase()}
                  </span>
                ),
              )}

              {provider.capabilities.selectable_audio && (
                <span>Audio tracks</span>
              )}

              {provider.capabilities.selectable_subtitles && (
                <span>Subtitles</span>
              )}

              {provider.capabilities.burned_in_subtitles && (
                <span>Burned-in subs</span>
              )}
            </div>

            <dl className="provider-stats">
              <div>
                <dt>Failures</dt>
                <dd>{provider.failure_count}</dd>
              </div>

              <div>
                <dt>Latency</dt>
                <dd>
                  {formatLatency(
                    provider.last_latency_ms,
                  )}
                </dd>
              </div>

              <div>
                <dt>Last success</dt>
                <dd>
                  {formatDate(
                    provider.last_success_at,
                  )}
                </dd>
              </div>

              <div>
                <dt>Last error</dt>
                <dd className="error-value">
                  {provider.last_error ?? "—"}
                </dd>
              </div>
            </dl>

            <div className="priority-row">
              <label>
                Priority

                <input
                  value={
                    priorities[
                      provider.provider_id
                    ] ?? ""
                  }
                  onChange={(event) =>
                    setPriorities((current) => ({
                      ...current,
                      [provider.provider_id]:
                        event.target.value,
                    }))
                  }
                />
              </label>

              <button
                className="button secondary compact"
                disabled={busy !== null}
                onClick={() =>
                  void savePriority(provider)
                }
              >
                Save
              </button>
            </div>

            <div className="provider-actions">
              <button
                className={
                  provider.enabled
                    ? "button danger"
                    : "button primary"
                }
                disabled={busy !== null}
                onClick={() =>
                  void toggle(provider)
                }
              >
                {provider.enabled
                  ? "Disable"
                  : "Enable"}
              </button>

              <button
                className="button secondary"
                disabled={busy !== null}
                onClick={() =>
                  void health(provider)
                }
              >
                Test health
              </button>

              {liveIds.has(provider.provider_id) ? (
                <Link
                  className="button secondary link-button"
                  to={`/admin/providers/${provider.provider_id}`}
                >
                  Edit
                </Link>
              ) : (
                <button className="button secondary" disabled={busy !== null}
                  onClick={() => void editFactory(provider.provider_id)}>
                  Edit / Create Override
                </button>
              )}
              {liveProviders.some(item => item.provider_id === provider.provider_id && !item.is_factory_override) && (
                <button className="button danger" disabled={busy !== null}
                  onClick={() => void removeProvider(provider.provider_id)}>
                  Delete
                </button>
              )}
            </div>
          </article>
        ))}
      </div>

      {liveProviders.some(
        (provider) => !provider.loaded,
      ) && (
        <article className="panel draft-provider-panel">
          <p className="section-kicker">
            DRAFTS
          </p>

          {liveProviders
            .filter((provider) => !provider.loaded)
            .map((provider) => (
              <div
                className="draft-provider-row"
                key={provider.provider_id}
              >
                <div>
                  <strong>
                    {provider.provider_id}
                  </strong>
                  <p className="muted">
                    Not activated yet
                  </p>
                </div>

                <Link
                  className="button secondary link-button"
                  to={`/admin/providers/${provider.provider_id}`}
                >
                  Edit draft
                </Link>
                {!provider.is_factory_override && <button className="button danger" disabled={busy !== null}
                  onClick={() => void removeProvider(provider.provider_id)}>
                  Delete
                </button>}
              </div>
            ))}
        </article>
      )}
    </section>
  );
}
