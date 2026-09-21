import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  getProviderLogs,
  listProviders,
  resolveEpisode,
  resolveMovie,
  testProvider,
  updateProvider,
} from "./api";

import type {
  PlaybackResolution,
  ProviderAdminView,
  ProviderEventView,
  ProviderStatus,
  ResolutionFailureDetail,
} from "./types";


function formatDate(value: string | null) {
  if (!value) return "—";

  const normalized =
    /Z$|[+-]\d\d:\d\d$/.test(value)
      ? value
      : `${value}Z`;

  const date = new Date(normalized);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("tr-TR");
}


function formatLatency(value: number | null) {
  if (value === null) return "—";

  if (value < 1) {
    return `${value.toFixed(2)} ms`;
  }

  return `${Math.round(value)} ms`;
}


function statusLabel(status: ProviderStatus) {
  const labels: Record<ProviderStatus, string> = {
    unknown: "Unknown",
    healthy: "Healthy",
    degraded: "Degraded",
    circuit_open: "Circuit Open",
    disabled: "Disabled",
  };

  return labels[status];
}


export default function AdminProviders() {
  const [providers, setProviders] =
    useState<ProviderAdminView[]>([]);

  const [priorities, setPriorities] =
    useState<Record<string, string>>({});

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [logs, setLogs] = useState<{
    provider: string;
    items: ProviderEventView[];
  } | null>(null);

  const [resolution, setResolution] =
    useState<PlaybackResolution | null>(null);

  const [resolutionFailure, setResolutionFailure] =
    useState<ResolutionFailureDetail | null>(null);

  const [mediaType, setMediaType] =
    useState<"movie" | "episode">("movie");

  const [tmdbId, setTmdbId] = useState("157336");
  const [season, setSeason] = useState("1");
  const [episode, setEpisode] = useState("1");


  async function refresh() {
    setError(null);

    try {
      const data = await listProviders();
      setProviders(data);

      setPriorities(
        Object.fromEntries(
          data.map((provider) => [
            provider.provider_id,
            String(provider.priority),
          ]),
        ),
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Provider listesi alınamadı",
      );
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => {
    void refresh();
  }, []);


  const summary = useMemo(() => {
    return {
      total: providers.length,
      enabled: providers.filter((p) => p.enabled).length,
      healthy: providers.filter(
        (p) => p.status === "healthy",
      ).length,
      problem: providers.filter(
        (p) =>
          p.status === "degraded" ||
          p.status === "circuit_open",
      ).length,
    };
  }, [providers]);


  async function toggleProvider(provider: ProviderAdminView) {
    const key = `toggle:${provider.provider_id}`;
    setBusy(key);
    setError(null);

    try {
      await updateProvider(provider.provider_id, {
        enabled: !provider.enabled,
      });

      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Update failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function savePriority(provider: ProviderAdminView) {
    const priority = Number(
      priorities[provider.provider_id],
    );

    if (!Number.isInteger(priority) || priority < 0) {
      setError("Priority 0 veya daha büyük tam sayı olmalı.");
      return;
    }

    const key = `priority:${provider.provider_id}`;
    setBusy(key);
    setError(null);

    try {
      await updateProvider(provider.provider_id, {
        priority,
      });

      setNotice(`${provider.name} priority güncellendi.`);
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Update failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function runHealth(provider: ProviderAdminView) {
    const key = `health:${provider.provider_id}`;
    setBusy(key);
    setError(null);
    setNotice(null);

    try {
      const result = await testProvider(provider.provider_id);

      setNotice(
        `${provider.name}: ${
          result.healthy ? "healthy" : "failed"
        } — ${formatLatency(result.latency_ms)}`,
      );

      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Health test failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function showLogs(provider: ProviderAdminView) {
    const key = `logs:${provider.provider_id}`;
    setBusy(key);
    setError(null);

    try {
      const items = await getProviderLogs(
        provider.provider_id,
      );

      setLogs({
        provider: provider.name,
        items,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Logs failed",
      );
    } finally {
      setBusy(null);
    }
  }


  async function runResolve(providerId?: string) {
    const parsedTmdb = Number(tmdbId);
    const parsedSeason = Number(season);
    const parsedEpisode = Number(episode);

    if (!Number.isInteger(parsedTmdb) || parsedTmdb <= 0) {
      setError("Geçerli bir TMDB ID gir.");
      return;
    }

    if (
      mediaType === "episode" &&
      (
        !Number.isInteger(parsedSeason) ||
        parsedSeason < 0 ||
        !Number.isInteger(parsedEpisode) ||
        parsedEpisode <= 0
      )
    ) {
      setError("Season / episode değerleri geçersiz.");
      return;
    }

    const key = providerId
      ? `resolve:${providerId}`
      : "resolve:fallback";

    setBusy(key);
    setError(null);
    setNotice(null);
    setResolution(null);
    setResolutionFailure(null);

    try {
      const result =
        mediaType === "movie"
          ? await resolveMovie(parsedTmdb, providerId)
          : await resolveEpisode(
              parsedTmdb,
              parsedSeason,
              parsedEpisode,
              providerId,
            );

      setResolution(result);
      setNotice(
        `Resolve başarılı: ${result.selected_provider_id}`,
      );

      await refresh();
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.detail &&
        typeof err.detail === "object" &&
        "message" in err.detail &&
        "attempts" in err.detail
      ) {
        setResolutionFailure(
          err.detail as ResolutionFailureDetail,
        );
        setError(null);
      } else {
        setError(
          err instanceof Error ? err.message : "Resolve failed",
        );
      }

      await refresh();
    } finally {
      setBusy(null);
    }
  }


  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <a className="back-link" href="/">
            ← Media App
          </a>

          <p className="eyebrow">ORBIS</p>
          <h1 className="admin-title">Provider Manager</h1>

          <p className="admin-subtitle">
            Sağlayıcı durumları, fallback sırası ve test araçları.
          </p>
        </div>

        <button
          className="button secondary"
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </header>

      <section className="summary-grid">
        <article className="summary-card">
          <span>Total</span>
          <strong>{summary.total}</strong>
        </article>

        <article className="summary-card">
          <span>Enabled</span>
          <strong>{summary.enabled}</strong>
        </article>

        <article className="summary-card">
          <span>Healthy</span>
          <strong>{summary.healthy}</strong>
        </article>

        <article className="summary-card">
          <span>Problems</span>
          <strong>{summary.problem}</strong>
        </article>
      </section>

      {error && (
        <div className="banner error-banner">
          {error}
        </div>
      )}

      {notice && (
        <div className="banner success-banner">
          {notice}
        </div>
      )}

      <section className="resolve-panel">
        <div>
          <p className="section-kicker">PLAYBACK TEST</p>
          <h2>Resolve tester</h2>
          <p>
            Fallback zincirini veya tek bir provider'ı
            gerçek manager üzerinden test eder.
          </p>
        </div>

        <div className="resolve-controls">
          <select
            value={mediaType}
            onChange={(event) =>
              setMediaType(
                event.target.value as "movie" | "episode",
              )
            }
          >
            <option value="movie">Movie</option>
            <option value="episode">Episode</option>
          </select>

          <input
            value={tmdbId}
            onChange={(event) =>
              setTmdbId(event.target.value)
            }
            inputMode="numeric"
            placeholder="TMDB ID"
          />

          {mediaType === "episode" && (
            <>
              <input
                value={season}
                onChange={(event) =>
                  setSeason(event.target.value)
                }
                inputMode="numeric"
                placeholder="Season"
              />

              <input
                value={episode}
                onChange={(event) =>
                  setEpisode(event.target.value)
                }
                inputMode="numeric"
                placeholder="Episode"
              />
            </>
          )}

          <button
            className="button primary"
            disabled={busy !== null}
            onClick={() => void runResolve()}
          >
            {busy === "resolve:fallback"
              ? "Testing…"
              : "Test fallback"}
          </button>
        </div>
      </section>

      {resolutionFailure && (
        <section className="resolution-panel failed-resolution">
          <div className="resolution-head">
            <div>
              <p className="section-kicker">RESULT</p>
              <h2>Resolve failed</h2>
              <p className="failure-message">
                {resolutionFailure.message}
              </p>
            </div>

            <span className="status failed">
              FAILED
            </span>
          </div>

          <div className="attempt-list">
            {resolutionFailure.attempts.map(
              (attempt, index) => (
                <div
                  className="attempt"
                  key={`${attempt.provider_id}-${index}`}
                >
                  <strong>{attempt.provider_id}</strong>

                  <span
                    className={`attempt-state ${attempt.status}`}
                  >
                    {attempt.status}
                  </span>

                  <span>
                    {formatLatency(attempt.latency_ms)}
                  </span>

                  <span className="attempt-error">
                    {attempt.error ?? "—"}
                  </span>
                </div>
              ),
            )}
          </div>
        </section>
      )}

      {resolution && (
        <section className="resolution-panel">
          <div className="resolution-head">
            <div>
              <p className="section-kicker">RESULT</p>
              <h2>{resolution.selected_provider_id}</h2>
            </div>

            <span className="status healthy">
              RESOLVED
            </span>
          </div>

          <div className="attempt-list">
            {resolution.attempts.map(
              (attempt, index) => (
                <div
                  className="attempt"
                  key={`${attempt.provider_id}-${index}`}
                >
                  <strong>{attempt.provider_id}</strong>

                  <span
                    className={`attempt-state ${attempt.status}`}
                  >
                    {attempt.status}
                  </span>

                  <span>
                    {formatLatency(attempt.latency_ms)}
                  </span>

                  <span className="attempt-error">
                    {attempt.error ?? "—"}
                  </span>
                </div>
              ),
            )}
          </div>
        </section>
      )}

      <section className="providers-section">
        <div className="section-heading">
          <div>
            <p className="section-kicker">REGISTRY</p>
            <h2>Providers</h2>
          </div>

          <span className="muted">
            Düşük priority önce denenir
          </span>
        </div>

        {loading ? (
          <div className="empty-state">
            Provider listesi yükleniyor…
          </div>
        ) : (
          <div className="provider-grid">
            {providers.map((provider) => (
              <article
                className="provider-card"
                key={provider.provider_id}
              >
                <div className="provider-card-head">
                  <div>
                    <h3>{provider.name}</h3>
                    <code>{provider.provider_id}</code>
                  </div>

                  <span
                    className={`status ${provider.status}`}
                  >
                    {statusLabel(provider.status)}
                  </span>
                </div>

                <div className="capabilities">
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
                      {formatDate(provider.last_success_at)}
                    </dd>
                  </div>

                  <div>
                    <dt>Last failure</dt>
                    <dd>
                      {formatDate(provider.last_failure_at)}
                    </dd>
                  </div>

                  <div>
                    <dt>Circuit until</dt>
                    <dd>
                      {formatDate(
                        provider.circuit_open_until,
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
                      inputMode="numeric"
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
                      void toggleProvider(provider)
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
                      void runHealth(provider)
                    }
                  >
                    Test health
                  </button>

                  <button
                    className="button secondary"
                    disabled={busy !== null}
                    onClick={() =>
                      void runResolve(
                        provider.provider_id,
                      )
                    }
                  >
                    Resolve
                  </button>

                  <button
                    className="button secondary"
                    disabled={busy !== null}
                    onClick={() =>
                      void showLogs(provider)
                    }
                  >
                    Logs
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {logs && (
        <section className="logs-panel">
          <div className="section-heading">
            <div>
              <p className="section-kicker">EVENT LOG</p>
              <h2>{logs.provider}</h2>
            </div>

            <button
              className="button secondary compact"
              onClick={() => setLogs(null)}
            >
              Close
            </button>
          </div>

          {logs.items.length === 0 ? (
            <div className="empty-state">
              Henüz event yok.
            </div>
          ) : (
            <div className="log-list">
              {logs.items.map((item) => (
                <article
                  className="log-entry"
                  key={item.id}
                >
                  <div>
                    <span
                      className={`log-level ${item.level}`}
                    >
                      {item.level}
                    </span>

                    <strong>{item.event}</strong>
                  </div>

                  <p>{item.message ?? "—"}</p>

                  <time>
                    {formatDate(item.created_at)}
                  </time>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
