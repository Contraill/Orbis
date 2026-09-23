import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Link,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  getCatalogDetails,
  getSeasonDetails,
  listPlaybackStates,
} from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import { ListActions } from "./LibraryPage";
import type {
  CatalogDetails,
  MediaType,
  PlaybackState,
  SeasonDetails,
} from "../types";


function parseId(value: string | undefined) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}


function parseSelectableSeason(value: string | null) {
  if (value === null) return 1;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}


function stateKey(
  tmdbId: number,
  season: number | null,
  episode: number | null,
) {
  return season === null || episode === null
    ? `movie:${tmdbId}`
    : `tv:${tmdbId}:s${season}:e${episode}`;
}


function actionLabel(state: PlaybackState | undefined) {
  if (state && !state.completed && state.resume_position_seconds > 0) {
    return "Resume";
  }
  return state?.completed ? "Play again" : "Play";
}


function progressLabel(state: PlaybackState | undefined) {
  if (!state || state.resume_position_seconds <= 0) return null;
  const minutes = Math.floor(state.resume_position_seconds / 60);
  return `${minutes} min watched`;
}


export default function DetailPage({
  mediaType,
}: {
  mediaType: MediaType;
}) {
  const { tmdbId } = useParams();
  const id = parseId(tmdbId);
  const { profile } = useProfile();
  const t = useText();
  const profileId = profile?.id ?? null;
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSeason = parseSelectableSeason(
    searchParams.get("season"),
  );
  const [details, setDetails] =
    useState<CatalogDetails | null>(null);
  const [states, setStates] = useState<PlaybackState[]>([]);
  const [season, setSeason] = useState<SeasonDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [seasonLoading, setSeasonLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seasonError, setSeasonError] =
    useState<string | null>(null);
  const currentDetails = details?.tmdb_id === id &&
    details.media_type === mediaType
    ? details
    : null;
  const seasonCount = currentDetails?.number_of_seasons &&
    currentDetails.number_of_seasons > 0
    ? currentDetails.number_of_seasons
    : 1;
  const seasons = Array.from(
    { length: seasonCount },
    (_, index) => index + 1,
  );
  const seasonNumber = seasons.includes(requestedSeason)
    ? requestedSeason
    : seasons[0];
  const activeSeason = season?.series_tmdb_id === id &&
    season.season_number === seasonNumber
    ? season
    : null;

  useEffect(() => {
    if (!id || !profileId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetails(null);
    setStates([]);
    setSeason(null);
    setSeasonError(null);
    void Promise.all([
      getCatalogDetails(mediaType, id),
      listPlaybackStates(profileId),
    ]).then(([nextDetails, nextStates]) => {
      if (!cancelled) {
        setDetails(nextDetails);
        setStates(nextStates);
      }
    }).catch((reason: unknown) => {
      if (!cancelled) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Content details could not be loaded",
        );
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [id, mediaType, profileId]);

  useEffect(() => {
    if (
      mediaType !== "tv" ||
      !id ||
      !profileId ||
      currentDetails?.media_type !== "tv"
    ) return;
    let cancelled = false;
    setSeasonLoading(true);
    setSeasonError(null);
    setSeason(null);
    void getSeasonDetails(id, seasonNumber)
      .then((nextSeason) => {
        if (!cancelled) setSeason(nextSeason);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setSeason(null);
          setSeasonError(
            reason instanceof Error
              ? reason.message
              : "Season could not be loaded",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setSeasonLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentDetails, id, mediaType, profileId, seasonNumber]);

  const statesByKey = useMemo(() => new Map(
    states.map((state) => [
      stateKey(
        state.tmdb_id,
        state.season_number,
        state.episode_number,
      ),
      state,
    ]),
  ), [states]);

  if (!profile) {
    return (
      <main className="catalog-status full-page-status">
        <div>
          <p>Select a profile before opening content.</p>
          <Link className="button primary link-button" to="/">
            Choose profile
          </Link>
        </div>
      </main>
    );
  }

  if (loading) {
    return <main className="catalog-status full-page-status">Loading…</main>;
  }

  if (!id || !details || error) {
    return (
      <main className="catalog-status full-page-status">
        <div>
          <p className="banner error-banner">
            {error ?? "Content not found"}
          </p>
          <Link className="back-link" to="/">← Browse</Link>
        </div>
      </main>
    );
  }

  const movieState = statesByKey.get(stateKey(id, null, null));
  const movieWatchPath = `/watch/${profile.id}/movie/${id}`;
  return (
    <div className="catalog-shell">
      <AppHeader />
      <main className="detail-page">
        <section
          className="detail-hero"
          style={details.backdrop_url ? {
            backgroundImage:
              `linear-gradient(90deg, #09090b 12%, ` +
              `rgba(9, 9, 11, .78) 52%, rgba(9, 9, 11, .2)), ` +
              `url(${details.backdrop_url})`,
          } : undefined}
        >
          <div className="detail-copy">
            <Link className="back-link" to="/">← {t("Browse")}</Link>
            <p className="section-kicker">
              {mediaType === "movie" ? "MOVIE" : "TV SERIES"}
            </p>
            <h1>{details.title}</h1>
            <div className="detail-meta">
              <span>{details.release_date?.slice(0, 4) ?? "—"}</span>
              {details.vote_average !== null ? (
                <span>★ {details.vote_average.toFixed(1)}</span>
              ) : null}
              {details.runtime_minutes ? (
                <span>{details.runtime_minutes} min</span>
              ) : null}
              {details.genres.slice(0, 3).map((genre) => (
                <span key={genre}>{genre}</span>
              ))}
            </div>
            <p className="detail-overview">
              {details.overview || "No overview is available."}
            </p>
            {mediaType === "movie" ? (
              <div className="detail-actions">
                <Link
                  className="button primary link-button play-button"
                  to={movieWatchPath}
                  state={{
                    title: details.title,
                    returnTo: `/movie/${id}`,
                  }}
                >
                  ▶ {t(actionLabel(movieState))}
                </Link>
                {progressLabel(movieState) ? (
                  <span>{progressLabel(movieState)}</span>
                ) : null}
              </div>
            ) : null}
            <ListActions item={{ media_type: mediaType, tmdb_id: id }} />
          </div>
        </section>

        {mediaType === "tv" ? (
          <section className="episodes-section">
            <div className="catalog-section-heading season-heading">
              <div>
                <p className="section-kicker">{t("Episodes")}</p>
                <h2>
                  {activeSeason?.name ?? `Season ${seasonNumber}`}
                </h2>
              </div>
              <label className="season-select">
                <span>{t("Season")}</span>
                <select
                  value={seasonNumber}
                  onChange={(event) => {
                    setSearchParams({ season: event.target.value });
                  }}
                >
                  {seasons.map((number) => (
                    <option key={number} value={number}>
                      {t("Season")} {number}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {seasonLoading ? (
              <div className="catalog-status">Loading episodes…</div>
            ) : null}
            {seasonError ? (
              <div className="banner error-banner">{seasonError}</div>
            ) : null}
            {!seasonLoading && !seasonError &&
            activeSeason?.episodes.length === 0 ? (
              <div className="empty-state">
                No episodes are available for this season.
              </div>
            ) : null}

            <div className="episode-list">
              {activeSeason?.episodes.map((episode) => {
                const episodeState = statesByKey.get(
                  stateKey(id, seasonNumber, episode.episode_number),
                );
                const watchPath = (
                  `/watch/${profile.id}/tv/${id}` +
                  `/season/${seasonNumber}` +
                  `/episode/${episode.episode_number}`
                );
                return (
                  <article
                    className="episode-card"
                    key={episode.episode_number}
                  >
                    <div className="episode-art">
                      {episode.still_url ? (
                        <img
                          src={episode.still_url}
                          alt=""
                          loading="lazy"
                        />
                      ) : (
                        <span>{episode.episode_number}</span>
                      )}
                    </div>
                    <div className="episode-copy">
                      <p>Episode {episode.episode_number}</p>
                      <h3>{episode.name || "Untitled episode"}</h3>
                      <small>
                        {episode.runtime_minutes
                          ? `${episode.runtime_minutes} min`
                          : episode.air_date ?? ""}
                        {progressLabel(episodeState)
                          ? ` · ${progressLabel(episodeState)}`
                          : ""}
                      </small>
                      <p>{episode.overview || "No overview available."}</p>
                    </div>
                    <Link
                      className="button primary link-button"
                      to={watchPath}
                      state={{
                        title: (
                          `${details.title} · ` +
                          `S${seasonNumber} E${episode.episode_number}`
                        ),
                        returnTo: `/tv/${id}?season=${seasonNumber}`,
                      }}
                    >
                      {t(actionLabel(episodeState))}
                    </Link>
                  </article>
                );
              })}
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
