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

export interface PlaybackResolution {
  selected_provider_id: string;
  attempts: ProviderAttempt[];
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
