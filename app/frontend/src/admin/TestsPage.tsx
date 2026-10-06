import {
  useEffect,
  useState,
} from "react";

import {
  ApiError,
  listProviders,
  resolveEpisode,
  resolveMovie,
} from "../api";

import type {
  AdminResolveResult,
  ProviderAdminView,
  ResolutionFailureDetail,
} from "../types";

import {
  formatLatency,
} from "./shared";


export default function TestsPage() {
  const [providers, setProviders] =
    useState<ProviderAdminView[]>([]);

  const [providerId, setProviderId] =
    useState("");

  const [mediaType, setMediaType] =
    useState<"movie" | "episode">("movie");

  const [tmdbId, setTmdbId] =
    useState("157336");

  const [season, setSeason] =
    useState("1");

  const [episode, setEpisode] =
    useState("1");

  const [result, setResult] =
    useState<AdminResolveResult | null>(null);

  const [failure, setFailure] =
    useState<ResolutionFailureDetail | null>(null);

  const [error, setError] =
    useState<string | null>(null);

  const [busy, setBusy] = useState(false);


  useEffect(() => {
    listProviders()
      .then(setProviders)
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Providers failed",
        );
      });
  }, []);


  async function run() {
    const id = Number(tmdbId);

    setBusy(true);
    setResult(null);
    setFailure(null);
    setError(null);

    try {
      const response =
        mediaType === "movie"
          ? await resolveMovie(
              id,
              providerId || undefined,
            )
          : await resolveEpisode(
              id,
              Number(season),
              Number(episode),
              providerId || undefined,
            );

      setResult(response);
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.detail &&
        typeof err.detail === "object" &&
        "message" in err.detail &&
        "attempts" in err.detail
      ) {
        setFailure(
          err.detail as ResolutionFailureDetail,
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : "Resolve failed",
        );
      }
    } finally {
      setBusy(false);
    }
  }


  const attempts =
    result?.attempts ??
    failure?.attempts ??
    [];

  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="section-kicker">
            PLAYBACK
          </p>

          <h2>Tests</h2>
        </div>
      </div>

      <article className="panel test-panel">
        <div className="test-fields">
          <select
            value={providerId}
            onChange={(event) =>
              setProviderId(event.target.value)
            }
          >
            <option value="">
              Fallback chain
            </option>

            {providers.map((provider) => (
              <option
                value={provider.provider_id}
                key={provider.provider_id}
              >
                {provider.name}
              </option>
            ))}
          </select>

          <select
            value={mediaType}
            onChange={(event) =>
              setMediaType(
                event.target.value as
                  | "movie"
                  | "episode",
              )
            }
          >
            <option value="movie">
              Movie
            </option>
            <option value="episode">
              Episode
            </option>
          </select>

          <input
            value={tmdbId}
            placeholder="TMDB ID"
            onChange={(event) =>
              setTmdbId(event.target.value)
            }
          />

          {mediaType === "episode" && (
            <>
              <input
                value={season}
                placeholder="Season"
                onChange={(event) =>
                  setSeason(event.target.value)
                }
              />

              <input
                value={episode}
                placeholder="Episode"
                onChange={(event) =>
                  setEpisode(event.target.value)
                }
              />
            </>
          )}

          <button
            className="button primary"
            disabled={busy}
            onClick={() => void run()}
          >
            {busy ? "Testing…" : "Run resolve"}
          </button>
        </div>
      </article>

      {error && (
        <div className="banner error-banner">
          {error}
        </div>
      )}

      {(result || failure) && (
        <article
          className={
            failure
              ? "resolution-panel failed-resolution"
              : "resolution-panel"
          }
        >
          <div className="resolution-head">
            <div>
              <p className="section-kicker">
                RESULT
              </p>

              <h2>
                {result
                  ? result.selected_provider_id
                  : "Resolve failed"}
              </h2>

              {failure && (
                <p className="failure-message">
                  {failure.message}
                </p>
              )}
            </div>

            <span
              className={
                failure
                  ? "status failed"
                  : "status healthy"
              }
            >
              {failure ? "FAILED" : "RESOLVED"}
            </span>
          </div>

          <div className="attempt-list">
            {attempts.map(
              (attempt, index) => (
                <div
                  className="attempt"
                  key={`${attempt.provider_id}-${index}`}
                >
                  <strong>
                    {attempt.provider_id}
                  </strong>

                  <span
                    className={`attempt-state ${attempt.status}`}
                  >
                    {attempt.status}
                  </span>

                  <span>
                    {formatLatency(
                      attempt.latency_ms,
                    )}
                  </span>

                  <span className="attempt-error">
                    {attempt.error ?? "—"}
                  </span>
                </div>
              ),
            )}
          </div>
          {result?.sources.length ? <div className="diagnostic-source-list">
            <h3>Resolved sources · profile preference order</h3>
            {result.sources.map((source, index) => <div className="diagnostic-source" key={`${source.provider_id}-${source.source_id ?? index}`}>
              <div><strong>{source.provider_id} · {source.source_label ?? source.source_id ?? "Source"}</strong><span className={`status ${source.status === "reachable" ? "healthy" : "failed"}`}>{source.status === "reachable" ? "Reachable" : "Failed"}</span></div>
              <small>{source.latency_ms == null ? "—" : formatLatency(source.latency_ms)}</small>
              <p>Quality: {source.quality_classes.join(", ") || "Unspecified"} · Audio: {source.audio_languages.join(", ") || "Unspecified"} {source.audio_kinds.length ? `(${source.audio_kinds.join(", ")})` : ""}</p>
              <p>Subtitles: {source.subtitle_languages.join(", ") || "None"}{source.burned_in_subtitles ? " · burned in" : ""}</p>
              <p>{source.ranking_reasons.join(" · ") || "Playable fallback"}{source.reason ? ` · ${source.reason}` : ""}</p>
            </div>)}
          </div> : null}
        </article>
      )}
    </section>
  );
}
