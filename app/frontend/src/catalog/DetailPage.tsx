import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getCatalogDetails, getCatalogRatings, getContinue, getSeasonDetails, listPlaybackStates, restartPlayback } from "../api";
import AppHeader from "../app/AppHeader";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import DetailActions from "./DetailActions";
import MediaCard from "./MediaCard";
import TrailerBackdrop from "./TrailerBackdrop";
import { useGlobalWatchTogether, type RoomContent } from "../watch/GlobalWatchTogether";
import type { CatalogDetails, MediaType, PlaybackState, SeasonDetails, CatalogItem, ContinueEntry } from "../types";

function action(state: PlaybackState | undefined) {
  if (state?.completed) return "Play Again";
  if (state && state.resume_position_seconds > 0) return "Resume";
  return "Play";
}
function episodePath(profileId: number, id: number, season: number, episode: number) {
  return `/watch/${profileId}/tv/${id}/season/${season}/episode/${episode}`;
}

export default function DetailPage({ mediaType }: { mediaType: MediaType }) {
  const { tmdbId } = useParams();
  const id = Number(tmdbId);
  const { profile } = useProfile();
  const t = useText();
  const navigate = useNavigate();
  const watch = useGlobalWatchTogether();
  const [params, setParams] = useSearchParams();
  const [details, setDetails] = useState<CatalogDetails | null>(null);
  const [states, setStates] = useState<PlaybackState[]>([]);
  const [continueEntry, setContinueEntry] = useState<ContinueEntry | null>(null);
  const [season, setSeason] = useState<SeasonDetails | null>(null);
  const [related, setRelated] = useState<CatalogItem[]>([]);
  const [imdb, setImdb] = useState<number | null>(null);
  const [trailerPlaying, setTrailerPlaying] = useState(false);
  const [detailsVisible, setDetailsVisible] = useState(false);
  const [loading, setLoading] = useState(true);
  const [seasonLoading, setSeasonLoading] = useState(false);
  const [error, setError] = useState("");
  const [seasonError, setSeasonError] = useState("");
  const [actionError, setActionError] = useState("");
  const [retry, setRetry] = useState(0);
  const seasonNumbers = useMemo(() => {
    if (!details) return [];
    const available = details.seasons.filter(s => s.season_number > 0 && s.episode_count > 0).map(s => s.season_number);
    return available.length ? available : Array.from({ length: Math.min(details.number_of_seasons ?? 1, 30) }, (_, index) => index + 1);
  }, [details]);
  const seasonNumber = seasonNumbers.includes(Number(params.get("season"))) ? Number(params.get("season")) : seasonNumbers[0] ?? 1;

  useEffect(() => {
    if (!profile || !Number.isInteger(id) || id < 1) return;
    let active = true;
    setLoading(true); setError(""); setDetails(null); setSeason(null); setRelated([]); setImdb(null); setTrailerPlaying(false); setDetailsVisible(false);
    Promise.all([getCatalogDetails(mediaType, id), listPlaybackStates(profile.id), getContinue(profile.id, mediaType)]).then(([data, playback, continued]) => {
      if (!active) return;
      setDetails(data); setStates(playback); setContinueEntry(continued.find(item => item.tmdb_id === id && item.media_type === mediaType) ?? null);
      void getCatalogRatings(mediaType, id).then(result => { if (active) setImdb(result.ratings.find(r => r.source === "imdb")?.average ?? null); }).catch(() => {});
      const unique = [...new Map(data.related.filter(r => r.tmdb_id !== id && (r.media_type === "movie" || r.media_type === "tv")).map(r => [`${r.media_type}:${r.tmdb_id}`, r])).values()].slice(0, 8);
      void Promise.allSettled(unique.map(ref => getCatalogDetails(ref.media_type, ref.tmdb_id))).then(results => {
        if (active) setRelated(results.filter((r): r is PromiseFulfilledResult<CatalogDetails> => r.status === "fulfilled").map(r => r.value));
      });
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : t("Request failed")); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, mediaType, profile?.id, profile?.locale, retry]);

  useEffect(() => {
    if (!profile || mediaType !== "tv" || !details) return;
    let active = true;
    setSeason(null); setSeasonError(""); setSeasonLoading(true);
    getSeasonDetails(id, seasonNumber).then(data => { if (active) setSeason(data); }).catch(reason => { if (active) setSeasonError(reason instanceof Error ? reason.message : t("Request failed")); }).finally(() => { if (active) setSeasonLoading(false); });
    return () => { active = false; };
  }, [profile?.id, profile?.locale, details, seasonNumber, mediaType, id]);

  if (!profile) return <div className="product-shell ambient"><main className="product-state"><Link to="/">{t("Select a profile")}</Link></main></div>;
  if (loading) return <div className="product-shell ambient"><AppHeader /><main className="product-loading" role="status">{t("Loading…")}</main></div>;
  if (!details || error) return <div className="product-shell ambient"><AppHeader /><main className="product-state" role="alert"><p>{error || t("Unavailable")}</p><button className="orbis-button" onClick={() => setRetry(current => current + 1)}>{t("Try again")}</button></main></div>;

  const movieState = states.find(s => s.media_type === "movie" && s.tmdb_id === id);
  const seriesStates = states.filter(s => s.media_type === "tv" && s.tmdb_id === id && s.season_number != null && s.episode_number != null);
  const currentEpisode = seriesStates.filter(s => !s.completed).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const firstSeason = seasonNumbers[0] ?? 1;
  const firstEpisode = season?.episodes[0]?.episode_number ?? 1;
  const primaryEpisode = continueEntry?.media_type === "tv" && continueEntry.season_number != null && continueEntry.episode_number != null
    ? { season: continueEntry.season_number, episode: continueEntry.episode_number, state: seriesStates.find(s => s.season_number === continueEntry.season_number && s.episode_number === continueEntry.episode_number) }
    : currentEpisode ? { season: currentEpisode.season_number!, episode: currentEpisode.episode_number!, state: currentEpisode } : { season: firstSeason, episode: firstEpisode, state: seriesStates.find(s => s.season_number === firstSeason && s.episode_number === firstEpisode) };
  const primaryPath = mediaType === "movie" ? `/watch/${profile.id}/movie/${id}` : episodePath(profile.id, id, primaryEpisode.season, primaryEpisode.episode);
  const primaryState = mediaType === "movie" ? movieState : primaryEpisode.state;
  const roles = (names: string[]) => details.credits.filter(c => names.includes(c.role)).slice(0, names.includes("Actor") ? 12 : 5);
  const credits = [
    ["Directed by", roles(["Director"])], ["Created by", roles(["Creator"])],
    ["Produced by", roles(["Producer", "Executive Producer"])], ["Cast", roles(["Actor"])],
  ] as const;
  async function begin(path: string, content: RoomContent, title: string, restart = false) {
    setActionError("");
    try {
      if (restart) await restartPlayback(profile!.id, content);
      const resume = !restart && primaryState?.tmdb_id === content.tmdb_id && primaryState.season_number === content.season_number && primaryState.episode_number === content.episode_number ? primaryState.resume_position_seconds : 0;
      await watch.start(content, path, { title, returnTo: window.location.pathname + window.location.search }, resume ?? 0);
    } catch (reason) { setActionError(reason instanceof Error ? reason.message : t("Request failed")); }
  }
  const primaryContent: RoomContent = { media_type: mediaType, tmdb_id: id, season_number: mediaType === "tv" ? primaryEpisode.season : null, episode_number: mediaType === "tv" ? primaryEpisode.episode : null };
  return <div className="product-shell detail-shell"><AppHeader /><main>
    <section className={`cinema-hero ${trailerPlaying && !detailsVisible ? "trailer-active" : ""}`} style={details.backdrop_url ? { backgroundImage: `url("${details.backdrop_url}")` } : undefined}>
      <TrailerBackdrop videos={details.videos} initiallyMuted={profile.trailer_muted} onPlayingChange={setTrailerPlaying} />
      <div className="cinema-shade" /><div className="cinema-copy" inert={trailerPlaying && !detailsVisible}>
        <button className="cinema-back" onClick={() => navigate(-1)}>← {t("Back")}</button>
        <span className="orbis-kicker">ORBIS / {t(mediaType === "movie" ? "Movies" : "Series")}</span>
        <h1>{details.title}</h1>
        <div className="cinema-meta"><span>{details.release_date?.slice(0, 4)}</span>{details.runtime_minutes ? <span>{details.runtime_minutes} {t("min")}</span> : null}{imdb != null ? <span className="imdb-score">IMDb {imdb.toFixed(1)}</span> : details.vote_average != null ? <span>★ {details.vote_average.toFixed(1)}</span> : null}{details.genres.slice(0, 3).map(genre => <span key={genre}>{genre}</span>)}</div>
        <p className="cinema-overview">{details.overview || t("No overview is available.")}</p>
        <div className="cinema-actions"><button className="orbis-button accent" onClick={() => void begin(primaryPath, primaryContent, details.title)}>▶ {t(continueEntry?.action === "next_episode" && mediaType === "tv" ? "Next episode" : action(primaryState))}</button>
          {primaryState && !primaryState.completed && primaryState.resume_position_seconds > 0 ? <button className="orbis-button ghost" onClick={() => void begin(primaryPath, primaryContent, details.title, true)}>{t("Start Over")}</button> : null}
          <DetailActions item={{ media_type: mediaType, tmdb_id: id }} />
        </div>
        {actionError ? <p role="alert" className="form-error">{actionError}</p> : null}
      </div>
      {trailerPlaying ? <button className="trailer-details-toggle" type="button" aria-pressed={detailsVisible} onClick={() => setDetailsVisible(value => !value)}>{t(detailsVisible ? "Hide details" : "Show details")}</button> : null}
    </section>
    <div className="detail-content">
      {details.original_title && details.original_title !== details.title ? <p className="original-title"><span>{t("Original title")}</span> {details.original_title}</p> : null}
      <div className="detail-facts">{credits.map(([label, people]) => people.length ? <div key={label}><h2>{t(label)}</h2><p>{people.map((person, index) => <span key={`${person.tmdb_id}:${index}`}><Link to={`/search?q=${encodeURIComponent(person.name)}`}>{person.name}</Link>{person.character && label === "Cast" ? <small> · {person.character}</small> : null}{index < people.length - 1 ? ", " : ""}</span>)}</p></div> : null)}
        {details.production_companies.length ? <div><h2>{t("Production")}</h2><p>{details.production_companies.map((company, index) => <span key={company.tmdb_id}><Link to={`/search?q=${encodeURIComponent(company.name)}`}>{company.name}</Link>{index < details.production_companies.length - 1 ? ", " : ""}</span>)}</p></div> : null}
      </div>
      {mediaType === "tv" ? <section className="orbis-episodes"><div className="orbis-section-heading"><div><span className="orbis-kicker">ORBIS / {t("Series")}</span><h2>{t("Episodes")}</h2></div><label>{t("Season")}<select value={seasonNumber} onChange={event => setParams({ season: event.target.value })}>{seasonNumbers.length ? seasonNumbers.map(n => <option key={n} value={n}>{details.seasons.find(s => s.season_number === n)?.name || `${t("Season")} ${n}`}</option>) : <option value="1">{t("Season")} 1</option>}</select></label></div>
        {seasonLoading ? <p role="status">{t("Loading…")}</p> : null}{seasonError ? <p role="alert">{seasonError}</p> : null}
        {!seasonLoading && !seasonError && !season?.episodes.length ? <p>{t("No episodes are available for this season.")}</p> : null}
        <div className="orbis-episode-list">{season?.episodes.map(episode => {
          const state = seriesStates.find(s => s.season_number === seasonNumber && s.episode_number === episode.episode_number);
          const path = episodePath(profile.id, id, seasonNumber, episode.episode_number);
          const content: RoomContent = { media_type: "tv", tmdb_id: id, season_number: seasonNumber, episode_number: episode.episode_number };
          const title = `${details.title} · S${seasonNumber} E${episode.episode_number}`;
          return <article className="orbis-episode" key={episode.episode_number}><button className="episode-still" onClick={() => void begin(path, content, title)}>{episode.still_url ? <img src={episode.still_url} alt="" loading="lazy" /> : <span>{episode.episode_number}</span>}</button><div><span className="orbis-kicker">{t("Episode")} {episode.episode_number} {episode.air_date ? `· ${episode.air_date}` : ""}</span><h3>{episode.name || t("Untitled episode")}</h3><p>{episode.overview}</p>{state && state.resume_position_seconds > 0 ? <small>{Math.floor(state.resume_position_seconds / 60)} {t("min watched")}</small> : null}</div><button className="orbis-button ghost" onClick={() => void begin(path, content, title)}>{t(action(state))} ↗</button></article>;
        })}</div>
      </section> : null}
      {related.length ? <section className="orbis-shelf related-shelf"><div className="orbis-shelf-heading"><h2>{t("More like this")}</h2></div><div className="orbis-shelf-track">{related.map(item => <MediaCard key={`${item.media_type}:${item.tmdb_id}`} item={item} />)}</div></section> : null}
    </div>
  </main></div>;
}
