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
  headers: Record<string, string>;
  expires_at: string | null;
}

export interface PlaybackResolution {
  selected_provider_id: string;
  sources: PlaybackSource[];
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
  resolution: PlaybackResolution;
  selected_source: PlaybackSource;
  selected_audio: AudioSelection;
  selected_subtitles: SubtitleSelection;
}

export interface PlaybackFailoverRequest
  extends PlaybackStateUpdate {
  failed_provider_id: string;
}

export interface ResolutionFailureDetail {
  message: string;
  attempts: ProviderAttempt[];
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
