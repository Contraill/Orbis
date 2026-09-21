export type ProviderStatus =
  | "unknown"
  | "healthy"
  | "degraded"
  | "circuit_open"
  | "disabled";

export interface ProviderCapabilities {
  movie: boolean;
  episode: boolean;
  protocols: string[];
  selectable_audio: boolean;
  selectable_subtitles: boolean;
  burned_in_subtitles: boolean;
}

export interface ProviderAdminView {
  provider_id: string;
  name: string;
  enabled: boolean;
  priority: number;
  status: ProviderStatus;
  capabilities: ProviderCapabilities;
  failure_count: number;
  circuit_open_until: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_health_check_at: string | null;
  last_latency_ms: number | null;
  last_error: string | null;
}

export interface ProviderHealthCheckReport {
  provider: ProviderAdminView;
  healthy: boolean;
  message: string | null;
  latency_ms: number;
}

export interface ProviderEventView {
  id: number;
  provider_id: string;
  level: string;
  event: string;
  message: string | null;
  created_at: string;
}

export interface ProviderAttempt {
  provider_id: string;
  status: "success" | "failed" | "skipped";
  latency_ms: number | null;
  error: string | null;
}

export type AudioKind =
  | "original"
  | "dub"
  | "commentary"
  | "unknown";

export interface AudioTrack {
  language: string | null;
  label: string | null;
  kind: AudioKind;
  track_id: string | null;
}

export type SubtitleKind =
  | "external"
  | "manifest"
  | "burned_in";

export interface SubtitleTrack {
  language: string | null;
  label: string | null;
  kind: SubtitleKind;
  url: string | null;
  format: string | null;
  track_id: string | null;
  forced: boolean;
}

export interface PlaybackSource {
  provider_id: string;
  url: string;
  protocol: "hls" | "dash" | "http";
  quality: string | null;
  audio_tracks: AudioTrack[];
  subtitle_tracks: SubtitleTrack[];
  expires_at: string | null;
}

export interface PlaybackResolutionSummary {
  selected_provider_id: string;
  attempts: ProviderAttempt[];
}

export interface PlaybackIdentity {
  profileId: number;
  mediaType: "movie" | "tv";
  tmdbId: number;
  seasonNumber?: number;
  episodeNumber?: number;
}

export interface PlaybackStateUpdate {
  position_seconds: number;
  duration_seconds: number | null;
  completed: boolean;
  last_provider_id: string | null;
  preferred_audio_language: string | null;
  preferred_audio_kind: AudioKind | null;
  subtitles_enabled: boolean;
  preferred_subtitle_language: string | null;
}

export interface PlaybackState extends PlaybackStateUpdate {
  profile_id: number;
  media_type: "movie" | "tv";
  tmdb_id: number;
  season_number: number | null;
  episode_number: number | null;
  resume_position_seconds: number;
  updated_at: string;
}

export interface AudioSelection {
  track: AudioTrack | null;
  matched_by: string;
}

export interface SubtitleSelection {
  enabled: boolean;
  can_disable: boolean;
  selected_track: SubtitleTrack | null;
  burned_in_track: SubtitleTrack | null;
}

export interface PlaybackSession {
  state: PlaybackState;
  resolution: PlaybackResolutionSummary;
  selected_source: PlaybackSource;
  source_session_id: string;
  source_expires_at: string | null;
  source_expiry_status:
    | "expired"
    | "near_expiry"
    | "healthy";
  refresh_at: string | null;
  selected_audio: AudioSelection;
  selected_subtitles: SubtitleSelection;
}

export interface PlaybackTransitionRequest
  extends PlaybackStateUpdate {
  preferred_audio_track_id: string | null;
  preferred_subtitle_track_id: string | null;
}

export interface PlaybackFailoverRequest
  extends PlaybackTransitionRequest {
  failed_provider_id: string;
}

export interface PlaybackRefreshRequest
  extends PlaybackTransitionRequest {
  source_session_id: string;
}

export interface PlaybackFailure {
  category: "network" | "media" | "other";
  resource_type: "manifest" | "segment" | "init" | "key" | "subtitle" | "unknown";
  http_status: number | null;
  code: number | null;
}

export interface PlaybackRecoverRequest extends PlaybackRefreshRequest {
  failure: PlaybackFailure;
}

export interface ResolutionFailureDetail {
  message: string;
  attempts: ProviderAttempt[];
}

export interface Profile {
  id: number;
  name: string;
  avatar: string | null;
}

export type MediaType = "movie" | "tv";

export interface CatalogItem {
  tmdb_id: number;
  media_type: MediaType;
  title: string;
  original_title: string | null;
  overview: string;
  poster_url: string | null;
  backdrop_url: string | null;
  release_date: string | null;
  vote_average: number | null;
}

export interface CatalogPage {
  page: number;
  total_pages: number;
  results: CatalogItem[];
}

export interface CatalogDetails extends CatalogItem {
  genres: string[];
  runtime_minutes: number | null;
  status: string | null;
  number_of_seasons: number | null;
  number_of_episodes: number | null;
}

export interface EpisodeSummary {
  episode_number: number;
  name: string;
  overview: string;
  air_date: string | null;
  still_url: string | null;
  runtime_minutes: number | null;
  vote_average: number | null;
}

export interface SeasonDetails {
  series_tmdb_id: number;
  season_tmdb_id: number;
  season_number: number;
  name: string;
  overview: string;
  air_date: string | null;
  poster_url: string | null;
  episodes: EpisodeSummary[];
}

export interface LiveProviderState {
  provider_id: string;
  name: string;
  loaded: boolean;
  has_active: boolean;
  draft_code: string;
  active_code: string | null;
  versions: string[];
}

export interface ProviderValidation {
  valid: boolean;
  errors: string[];
  provider: {
    provider_id: string;
    name: string;
    capabilities: ProviderCapabilities;
  } | null;
}
