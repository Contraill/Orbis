import {
  useEffect,
  useState,
} from "react";

import {
  getDiscoveryErrors,
  getProviderLogs,
  listProviders,
} from "../api";

import type {
  ProviderAdminView,
  ProviderEventView,
} from "../types";

import {
  formatDate,
  formatLatency,
  StatusBadge,
} from "./shared";


export default function DiagnosticsPage() {
  const [providers, setProviders] =
    useState<ProviderAdminView[]>([]);

  const [errors, setErrors] =
    useState<Record<string, string>>({});

  const [selected, setSelected] =
    useState("");

  const [logs, setLogs] =
    useState<ProviderEventView[]>([]);

  const [error, setError] =
    useState<string | null>(null);

  const [busy, setBusy] = useState(false);


  async function refresh() {
    setBusy(true);
    setError(null);

    try {
      const [providerData, discovery, logData] =
        await Promise.all([
          listProviders(),
          getDiscoveryErrors(),
          selected
            ? getProviderLogs(selected, 100)
            : Promise.resolve([]),
        ]);

      setProviders(providerData);
      setErrors(discovery);
      setLogs(logData);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Diagnostics refresh failed",
      );
    } finally {
      setBusy(false);
    }
  }


  useEffect(() => {
    void refresh();
  }, []);


  async function loadLogs(providerId: string) {
    setSelected(providerId);
    setError(null);

    if (!providerId) {
      setLogs([]);
      return;
    }

    try {
      setLogs(
        await getProviderLogs(providerId, 100),
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Provider logs failed",
      );
    }
  }


  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="section-kicker">
            HEALTH
          </p>

          <h2>Diagnostics</h2>
        </div>

        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="banner error-banner">
          {error}
        </div>
      )}

      {Object.keys(errors).length > 0 && (
        <article className="discovery-error-panel">
          <p className="section-kicker">
            DISCOVERY ERRORS
          </p>

          {Object.entries(errors).map(
            ([adapter, message]) => (
              <div
                className="discovery-error-row"
                key={adapter}
              >
                <strong>{adapter}</strong>
                <code>{message}</code>
              </div>
            ),
          )}
        </article>
      )}

      <div className="diagnostic-grid">
        {providers.map((provider) => (
          <article
            className="diagnostic-card"
            key={provider.provider_id}
          >
            <div className="provider-card-head">
              <strong>{provider.name}</strong>

              <StatusBadge
                status={provider.status}
              />
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
                <dt>Circuit until</dt>
                <dd>
                  {formatDate(
                    provider.circuit_open_until,
                  )}
                </dd>
              </div>

              <div>
                <dt>Last failure</dt>
                <dd>
                  {formatDate(
                    provider.last_failure_at,
                  )}
                </dd>
              </div>
            </dl>
          </article>
        ))}
      </div>

      <article className="panel diagnostics-logs">
        <div className="page-heading">
          <div>
            <p className="section-kicker">
              EVENT LOG
            </p>

            <h3>Provider logs</h3>
          </div>

          <select
            value={selected}
            onChange={(event) =>
              void loadLogs(event.target.value)
            }
          >
            <option value="">
              Select provider
            </option>

            {providers.map((provider) => (
              <option
                key={provider.provider_id}
                value={provider.provider_id}
              >
                {provider.name}
              </option>
            ))}
          </select>
        </div>

        <div className="log-list">
          {logs.map((item) => (
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
      </article>
    </section>
  );
}
