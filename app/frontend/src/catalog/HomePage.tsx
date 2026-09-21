import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";

import {
  getCatalogDetails,
  getSeasonDetails,
  getTrending,
  listPlaybackStates,
  searchCatalog,
} from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import type {
  CatalogItem,
  EpisodeSummary,
  PlaybackState,
} from "../types";
import MediaCard from "./MediaCard";
import ProfileSelection from "./ProfileSelection";


interface ContinueItem {
  state: PlaybackState;
  item: CatalogItem;
  episode: EpisodeSummary | null;
}


function progressPercent(state: PlaybackState) {
  if (!state.duration_seconds) return 0;
  return Math.min(
    100,
    Math.max(0, (state.position_seconds / state.duration_seconds) * 100),
  );
}


async function loadContinueItem(
  state: PlaybackState,
): Promise<ContinueItem | null> {
  try {
    if (
      state.media_type === "tv" &&
      state.season_number !== null &&
      state.episode_number !== null
    ) {
      const [item, season] = await Promise.all([
        getCatalogDetails("tv", state.tmdb_id),
        getSeasonDetails(
          state.tmdb_id,
          state.season_number,
        ),
      ]);
      return {
        state,
        item,
        episode: season.episodes.find(
          (episode) =>
            episode.episode_number === state.episode_number,
        ) ?? null,
      };
    }
    const item = await getCatalogDetails(
      state.media_type,
      state.tmdb_id,
    );
    return { state, item, episode: null };
  } catch {
    return null;
  }
}


function ContinueCard({ entry }: { entry: ContinueItem }) {
  const { state, item, episode } = entry;
  const watchPath = state.media_type === "movie"
    ? `/watch/${state.profile_id}/movie/${state.tmdb_id}`
    : (
      `/watch/${state.profile_id}/tv/${state.tmdb_id}` +
      `/season/${state.season_number}` +
      `/episode/${state.episode_number}`
    );
  const detailPath = `/${state.media_type}/${state.tmdb_id}`;

  return (
    <article className="continue-card">
      <Link className="continue-art" to={detailPath}>
        {item.backdrop_url || item.poster_url ? (
          <img
            src={item.backdrop_url ?? item.poster_url ?? ""}
            alt=""
            loading="lazy"
          />
        ) : (
          <span>{item.title.slice(0, 1)}</span>
        )}
        <div className="progress-track" aria-hidden="true">
          <span
            style={{ width: `${progressPercent(state)}%` }}
          />
        </div>
      </Link>
      <div className="continue-copy">
        <Link to={detailPath}>{item.title}</Link>
        <small>
          {state.media_type === "tv"
            ? (
              `S${state.season_number} E${state.episode_number}` +
              (episode?.name ? ` · ${episode.name}` : "")
            )
            : "Movie"}
        </small>
        <Link
          className="button primary compact link-button"
          to={watchPath}
          state={{ title: item.title, returnTo: detailPath }}
        >
          Resume
        </Link>
      </div>
    </article>
  );
}


export default function HomePage() {
  const { profile } = useProfile();
  const profileId = profile?.id ?? null;
  const [trending, setTrending] = useState<CatalogItem[]>([]);
  const [trendingLoading, setTrendingLoading] = useState(false);
  const [trendingError, setTrendingError] =
    useState<string | null>(null);
  const [continueItems, setContinueItems] =
    useState<ContinueItem[]>([]);
  const [continueLoading, setContinueLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [searchTitle, setSearchTitle] = useState("");
  const [searchResults, setSearchResults] =
    useState<CatalogItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] =
    useState<string | null>(null);
  const searchRequestRef = useRef(0);

  useEffect(() => {
    if (!profileId) return;
    let cancelled = false;
    setTrendingLoading(true);
    setTrendingError(null);
    void getTrending("day")
      .then((page) => {
        if (!cancelled) setTrending(page.results);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setTrendingError(
            reason instanceof Error
              ? reason.message
              : "Trending titles could not be loaded",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setTrendingLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profileId]);

  useEffect(() => {
    if (!profileId) return;
    let cancelled = false;
    setContinueLoading(true);
    void (async () => {
      try {
        const states = await listPlaybackStates(profileId);
        const resumable = states
          .filter((state) => (
            !state.completed && state.resume_position_seconds > 0
          ))
          .slice(0, 12);
        const entries = await Promise.all(
          resumable.map(loadContinueItem),
        );
        if (!cancelled) {
          setContinueItems(
            entries.filter(
              (entry): entry is ContinueItem => entry !== null,
            ),
          );
        }
      } catch {
        if (!cancelled) setContinueItems([]);
      } finally {
        if (!cancelled) setContinueLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [profileId]);

  if (!profile) {
    return <ProfileSelection />;
  }

  const submitSearch = async (event: FormEvent) => {
    event.preventDefault();
    const submitted = query.trim();
    if (!submitted) {
      setSearchTitle("");
      setSearchResults([]);
      setSearchError(null);
      return;
    }

    const requestId = ++searchRequestRef.current;
    setSearchTitle(submitted);
    setSearchLoading(true);
    setSearchError(null);
    try {
      const page = await searchCatalog(submitted);
      if (requestId === searchRequestRef.current) {
        setSearchResults(page.results);
      }
    } catch (reason) {
      if (requestId === searchRequestRef.current) {
        setSearchError(
          reason instanceof Error
            ? reason.message
            : "Search failed",
        );
        setSearchResults([]);
      }
    } finally {
      if (requestId === searchRequestRef.current) {
        setSearchLoading(false);
      }
    }
  };

  const clearSearch = () => {
    searchRequestRef.current += 1;
    setQuery("");
    setSearchTitle("");
    setSearchResults([]);
    setSearchError(null);
    setSearchLoading(false);
  };

  return (
    <div className="catalog-shell">
      <AppHeader />
      <main className="catalog-main">
        <section className="catalog-hero">
          <p className="eyebrow">WELCOME BACK, {profile.name}</p>
          <h1>Find something worth watching.</h1>
          <form className="catalog-search" onSubmit={submitSearch}>
            <label className="sr-only" htmlFor="catalog-query">
              Search movies and TV series
            </label>
            <input
              id="catalog-query"
              type="search"
              value={query}
              placeholder="Search movies and TV series"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button className="button primary" type="submit">
              Search
            </button>
            {searchTitle ? (
              <button
                className="button secondary"
                type="button"
                onClick={clearSearch}
              >
                Clear
              </button>
            ) : null}
          </form>
        </section>

        {!searchTitle && (continueLoading || continueItems.length > 0) ? (
          <section className="catalog-section">
            <div className="catalog-section-heading">
              <div>
                <p className="section-kicker">YOUR PROGRESS</p>
                <h2>Continue Watching</h2>
              </div>
            </div>
            {continueLoading ? (
              <div className="catalog-status">Loading progress…</div>
            ) : (
              <div className="continue-grid">
                {continueItems.map((entry) => (
                  <ContinueCard
                    key={
                      `${entry.state.media_type}-` +
                      `${entry.state.tmdb_id}-` +
                      `${entry.state.season_number ?? "movie"}-` +
                      `${entry.state.episode_number ?? "movie"}`
                    }
                    entry={entry}
                  />
                ))}
              </div>
            )}
          </section>
        ) : null}

        <section className="catalog-section">
          <div className="catalog-section-heading">
            <div>
              <p className="section-kicker">
                {searchTitle ? "SEARCH" : "TRENDING TODAY"}
              </p>
              <h2>
                {searchTitle
                  ? `Results for “${searchTitle}”`
                  : "Popular right now"}
              </h2>
            </div>
          </div>

          {(searchLoading || (!searchTitle && trendingLoading)) ? (
            <div className="catalog-status">Loading titles…</div>
          ) : null}
          {(searchError || (!searchTitle && trendingError)) ? (
            <div className="banner error-banner">
              {searchError ?? trendingError}
            </div>
          ) : null}
          {!searchLoading && searchTitle && !searchError &&
          searchResults.length === 0 ? (
            <div className="empty-state">
              No movies or series matched this search.
            </div>
          ) : null}

          <div className="media-grid">
            {(searchTitle ? searchResults : trending).map((item) => (
              <MediaCard
                key={`${item.media_type}-${item.tmdb_id}`}
                item={item}
              />
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
