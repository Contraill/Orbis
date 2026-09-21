import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getDiscoveryErrors,
  listLiveProviders,
  listProviders,
} from "../api";

import type {
  ProviderAdminView,
} from "../types";

import {
  StatusBadge,
} from "./shared";


export default function OverviewPage() {
  const [providers, setProviders] =
    useState<ProviderAdminView[]>([]);

  const [liveCount, setLiveCount] =
    useState(0);

  const [discoveryErrors, setDiscoveryErrors] =
    useState<Record<string, string>>({});

  const [error, setError] =
    useState<string | null>(null);


  useEffect(() => {
    Promise.all([
      listProviders(),
      listLiveProviders(),
      getDiscoveryErrors(),
    ])
      .then(([items, live, errors]) => {
        setProviders(items);
        setLiveCount(live.length);
        setDiscoveryErrors(errors);
      })
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Overview failed",
        );
      });
  }, []);


  const enabled = useMemo(
    () => providers.filter((p) => p.enabled),
    [providers],
  );

  const healthy = providers.filter(
    (p) => p.status === "healthy",
  ).length;

  const problems =
    providers.filter(
      (p) =>
        p.status === "degraded" ||
        p.status === "circuit_open",
    ).length +
    Object.keys(discoveryErrors).length;


  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="section-kicker">
            SYSTEM
          </p>
          <h2>Overview</h2>
        </div>
      </div>

      {error && (
        <div className="banner error-banner">
          {error}
        </div>
      )}

      <div className="summary-grid">
        <article className="summary-card">
          <span>Providers</span>
          <strong>{providers.length}</strong>
        </article>

        <article className="summary-card">
          <span>Enabled</span>
          <strong>{enabled.length}</strong>
        </article>

        <article className="summary-card">
          <span>Healthy</span>
          <strong>{healthy}</strong>
        </article>

        <article className="summary-card">
          <span>Problems</span>
          <strong>{problems}</strong>
        </article>
      </div>

      <div className="overview-grid">
        <article className="panel">
          <p className="section-kicker">
            FALLBACK CHAIN
          </p>

          <div className="fallback-chain">
            {enabled.length === 0 ? (
              <span className="muted">
                No enabled providers
              </span>
            ) : (
              enabled
                .slice()
                .sort(
                  (a, b) =>
                    a.priority - b.priority,
                )
                .map((provider, index) => (
                  <div
                    key={provider.provider_id}
                    className="fallback-node"
                  >
                    <span className="fallback-index">
                      {index + 1}
                    </span>

                    <strong>
                      {provider.name}
                    </strong>

                    <StatusBadge
                      status={provider.status}
                    />
                  </div>
                ))
            )}
          </div>
        </article>

        <article className="panel">
          <p className="section-kicker">
            LIVE PROVIDERS
          </p>

          <strong className="large-value">
            {liveCount}
          </strong>

          <p className="muted">
            Runtime-editable provider adapters
          </p>
        </article>
      </div>
    </section>
  );
}
