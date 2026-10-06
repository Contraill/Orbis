import type {
  CatalogDetails,
  AdminResolveResult,
  CatalogPage,
  LiveProviderState,
  PlaybackFailoverRequest,
  PlaybackIdentity,
  PlaybackRefreshRequest,
  PlaybackRecoverRequest,
  PlaybackResolutionSummary,
  PlaybackSession,
  PlaybackState,
  PlaybackStateUpdate,
  Profile,
  ProfileInput,
  ProviderAdminView,
  ProviderEventView,
  ProviderHealthCheckReport,
  ProviderValidation,
  SeasonDetails,
  SetupStatus, ContentSelection, LibraryItem, ContinueEntry, HistoryEntry,
} from "./types";


const PROVIDERS = "/api/admin/providers";
const EDITOR = "/api/admin/provider-editor";

export function createFactoryOverride(providerId: string) {
  return request<LiveProviderState>(`${EDITOR}/${encodeURIComponent(providerId)}/override`, { method: "POST" });
}

export function revertToFactory(providerId: string) {
  return request<LiveProviderState>(`${EDITOR}/${encodeURIComponent(providerId)}/revert-to-factory`, { method: "POST" });
}

export function choosePlayback(identity: PlaybackIdentity, payload: PlaybackRefreshRequest) {
  return request<PlaybackSession>(`${playbackPath(identity)}/choices`, {
    method: "POST", body: JSON.stringify(payload),
  });
}


function playbackPath(identity: PlaybackIdentity) {
  const root =
    `/api/playback/profiles/${identity.profileId}`;

  if (identity.mediaType === "movie") {
    return `${root}/movie/${identity.tmdbId}`;
  }

  return (
    `${root}/tv/${identity.tmdbId}` +
    `/season/${identity.seasonNumber}` +
    `/episode/${identity.episodeNumber}`
  );
}


export class ApiError extends Error {
  code?: string;
  status: number;
  detail: unknown;

  constructor(
    status: number,
    message: string,
    detail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}


export async function request<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = sessionStorage.getItem("orbis.owner-session");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (url.startsWith("/api/catalog/")) {
    const profileId = localStorage.getItem("media-app.selected-profile.v1");
    if (profileId) url += `${url.includes("?") ? "&" : "?"}profile_id=${encodeURIComponent(profileId)}`;
  }

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (url.startsWith("/api/playback/profiles/")) {
    const saved = sessionStorage.getItem("orbis.client-session");
    if (saved) {
      const client = JSON.parse(saved) as { id: string; profile_id: number };
      if (url.startsWith(`/api/playback/profiles/${client.profile_id}/`)) headers.set("X-Orbis-Session", client.id);
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let detail: unknown = null;
    let code: string | undefined;

    try {
      const body = await response.json();
      detail = body.detail;
      code = body.error?.code;

      if (body.error?.message) {
        message = body.error.message;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      } else if (body.detail?.message) {
        message = body.detail.message;
      } else if (Array.isArray(body.detail)) {
        const messages = body.detail
          .map((item: unknown) => {
            if (
              item &&
              typeof item === "object" &&
              "msg" in item
            ) {
              return String(item.msg);
            }
            return null;
          })
          .filter(
            (item: string | null): item is string =>
              item !== null,
          );

        if (messages.length > 0) {
          message = messages.join("; ");
        }
      }
    } catch {
      // Keep HTTP status.
    }

    const error = new ApiError(
      response.status,
      message,
      detail,
    );
    error.code = code;
    throw error;
  }

  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export const getSetup = () => request<SetupStatus>("/api/setup");
export const setSetupLocale = (locale: Profile["locale"]) => request("/api/setup/locale", { method: "PUT", body: JSON.stringify({ locale }) });
export const bootstrapOwner = (name: string, password: string, locale?: Profile["locale"]) => request<{ owner_id: number; token: string }>("/api/setup/owner", { method: "POST", body: JSON.stringify({ name, password, locale }) });
export const loginOwner = (password: string) => request<{ owner_id: number; token: string }>("/api/setup/login", { method: "POST", body: JSON.stringify({ password }) });
export const ownerSession = () => request<{ owner_id: number }>("/api/setup/session");
export const logoutOwner = () => request("/api/setup/logout", { method: "POST" });
export const editProfile = (id: number, values: Partial<Omit<Profile, "id" | "is_owner">>) => request<Profile>(`/api/profiles/${id}`, { method: "PATCH", body: JSON.stringify(values) });
export const deleteOwnProfile = (id: number, confirmName: string) => request<void>(`/api/profiles/${id}/self-delete`, {
  method: "POST",
  headers: { "X-Profile-Id": String(id) },
  body: JSON.stringify({ confirm_name: confirmName }),
});
const library = (id: number) => `/api/library/profiles/${id}`;
export const getContinue = (id: number, kind = "all") => request<ContinueEntry[]>(`${library(id)}/continue?kind=${kind}`);
export const hideContinue = (id: number, item: ContentSelection) => request(`${library(id)}/continue/hide`, { method: "POST", body: JSON.stringify({ media_type: item.media_type, tmdb_id: item.tmdb_id }) });
export const getMyList = (id: number, kind = "all") => request<LibraryItem[]>(`${library(id)}/my-list?kind=${kind}`);
export const getHistory = (id: number) => request<HistoryEntry[]>(`${library(id)}/history`);
export const setListIntent = (id: number, item: ContentSelection, enabled: boolean, negative = false) => request(`${library(id)}/${negative ? "not-interested" : "my-list"}`, { method: "PUT", body: JSON.stringify({ media_type: item.media_type, tmdb_id: item.tmdb_id, enabled }) });
export const restartPlayback = (id: number, item: ContentSelection & { season_number?: number | null; episode_number?: number | null }) => request(`${library(id)}/restart`, { method: "POST", body: JSON.stringify(item) });


export function listProviders() {
  return request<ProviderAdminView[]>(PROVIDERS);
}


export function updateProvider(
  providerId: string,
  payload: {
    enabled?: boolean;
    priority?: number;
  },
) {
  return request<ProviderAdminView>(
    `${PROVIDERS}/${providerId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}


export function testProvider(providerId: string) {
  return request<ProviderHealthCheckReport>(
    `${PROVIDERS}/${providerId}/test`,
    {
      method: "POST",
    },
  );
}


export function getProviderLogs(
  providerId: string,
  limit = 50,
) {
  return request<ProviderEventView[]>(
    `${PROVIDERS}/${providerId}/logs?limit=${limit}`,
  );
}


export function getDiscoveryErrors() {
  return request<Record<string, string>>(
    `${PROVIDERS}/discovery-errors`,
  );
}


export function resolveMovie(
  tmdbId: number,
  providerId?: string,
) {
  const url = providerId
    ? `${PROVIDERS}/${providerId}/resolve-test/movie/${tmdbId}`
    : `${PROVIDERS}/resolve-test/movie/${tmdbId}`;

  return request<AdminResolveResult>(url, {
    method: "POST",
  });
}


export function resolveEpisode(
  tmdbId: number,
  season: number,
  episode: number,
  providerId?: string,
) {
  const suffix =
    `tv/${tmdbId}/season/${season}/episode/${episode}`;

  const url = providerId
    ? `${PROVIDERS}/${providerId}/resolve-test/${suffix}`
    : `${PROVIDERS}/resolve-test/${suffix}`;

  return request<AdminResolveResult>(url, {
    method: "POST",
  });
}


export function getPlaybackState(
  identity: PlaybackIdentity,
) {
  return request<PlaybackState | null>(
    `${playbackPath(identity)}/state`,
  );
}


export function savePlaybackState(
  identity: PlaybackIdentity,
  state: PlaybackStateUpdate,
  keepalive = false,
) {
  return request<PlaybackState>(
    `${playbackPath(identity)}/state`,
    {
      method: "PUT",
      body: JSON.stringify(state),
      keepalive,
    },
  );
}


export function resolvePlayback(
  identity: PlaybackIdentity,
) {
  return request<PlaybackSession>(
    `${playbackPath(identity)}/resolve`,
    { method: "POST" },
  );
}


export function failoverPlayback(
  identity: PlaybackIdentity,
  state: PlaybackFailoverRequest,
) {
  return request<PlaybackSession>(
    `${playbackPath(identity)}/failover`,
    {
      method: "POST",
      body: JSON.stringify(state),
    },
  );
}


export function refreshPlayback(
  identity: PlaybackIdentity,
  state: PlaybackRefreshRequest,
) {
  return request<PlaybackSession>(
    `${playbackPath(identity)}/refresh`,
    {
      method: "POST",
      body: JSON.stringify(state),
    },
  );
}


export function recoverPlayback(identity: PlaybackIdentity, state: PlaybackRecoverRequest) {
  return request<PlaybackSession>(`${playbackPath(identity)}/recover`, {
    method: "POST",
    body: JSON.stringify(state),
  });
}


export function listProfiles() {
  return request<Profile[]>("/api/profiles");
}


export function createProfile(profile: ProfileInput) {
  return request<Profile>("/api/profiles", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}


export function getTrending(window: "day" | "week" = "day") {
  return request<CatalogPage>(
    `/api/catalog/trending?window=${window}`,
  );
}


export function searchCatalog(query: string, page = 1) {
  const params = new URLSearchParams({
    query,
    page: String(page),
  });
  return request<CatalogPage>(
    `/api/catalog/search?${params.toString()}`,
  );
}


export function getCatalogDetails(
  mediaType: "movie" | "tv",
  tmdbId: number,
) {
  return request<CatalogDetails>(
    `/api/catalog/${mediaType}/${tmdbId}`,
  );
}
export function getCatalogRatings(mediaType: "movie" | "tv", tmdbId: number) {
  return request<{ ratings: { source: string; average: number; votes: number }[] }>(`/api/catalog/${mediaType}/${tmdbId}/ratings`);
}


export function getSeasonDetails(
  tmdbId: number,
  seasonNumber: number,
) {
  return request<SeasonDetails>(
    `/api/catalog/tv/${tmdbId}/season/${seasonNumber}`,
  );
}


export function listPlaybackStates(profileId: number) {
  return request<PlaybackState[]>(
    `/api/playback/profiles/${profileId}/states`,
  );
}


export function listLiveProviders() {
  return request<LiveProviderState[]>(EDITOR);
}


export function createLiveProvider(
  providerId: string,
  name: string,
) {
  return request<LiveProviderState>(EDITOR, {
    method: "POST",
    body: JSON.stringify({
      provider_id: providerId,
      name,
    }),
  });
}


export function deleteLiveProvider(providerId: string) {
  return request<void>(`${EDITOR}/${encodeURIComponent(providerId)}`, {
    method: "DELETE",
  });
}


export function getLiveProvider(providerId: string) {
  return request<LiveProviderState>(
    `${EDITOR}/${providerId}`,
  );
}


export function saveProviderDraft(
  providerId: string,
  code: string,
) {
  return request<LiveProviderState>(
    `${EDITOR}/${providerId}/draft`,
    {
      method: "PUT",
      body: JSON.stringify({ code }),
    },
  );
}


export function validateProviderDraft(
  providerId: string,
) {
  return request<ProviderValidation>(
    `${EDITOR}/${providerId}/validate`,
    {
      method: "POST",
    },
  );
}


export function activateProviderDraft(
  providerId: string,
) {
  return request<LiveProviderState>(
    `${EDITOR}/${providerId}/activate`,
    {
      method: "POST",
    },
  );
}


export function rollbackProvider(
  providerId: string,
  version: string,
) {
  return request<LiveProviderState>(
    `${EDITOR}/${providerId}/rollback/${encodeURIComponent(version)}`,
    {
      method: "POST",
    },
  );
}


export interface ProviderSetting {
  key: string; label: string; description: string;
  type: "string" | "integer" | "boolean" | "enum" | "url" | "secret";
  required: boolean; sensitive: boolean; default: unknown;
  minimum: number | null; maximum: number | null; max_length: number; choices: string[];
}
export interface ProviderSettingsView {
  schema: ProviderSetting[]; values: Record<string, unknown>;
  configured_secrets: string[]; schema_available: boolean;
}

export function getProviderSettings(
  providerId: string,
) {
  return request<ProviderSettingsView>(
    `${EDITOR}/${providerId}/settings`,
  );
}


export function saveProviderSettings(
  providerId: string,
  settings: Record<string, unknown>,
) {
  return request<ProviderSettingsView>(
    `${EDITOR}/${providerId}/settings`,
    {
      method: "PUT",
      body: JSON.stringify({ settings }),
    },
  );
}

export type SearchResult = {
  key: string;
  kind: "movie" | "tv" | "person" | "company";
  tmdb_id: number;
  title: string;
  roles: string[];
  display_locale?: string;
  poster_url?: string | null; backdrop_url?: string | null; overview?: string;
  release_date?: string | null; vote_average?: number | null;
};
export type SearchPage = { results: SearchResult[]; next_cursor: string | null; warning?: string | null };
export type GenreSearchResult = { genre_id: number; title: string; scope: "all" | "movie" | "tv" };
export function searchGenres(query: string, kind: "all" | "movie" | "tv", signal?: AbortSignal) {
  return request<{ results: GenreSearchResult[] }>(`/api/catalog/genres?${new URLSearchParams({ query, kind })}`, { signal });
}
export function unifiedSearch(query: string, kind: string, online: boolean, cursor?: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ query, kind, online: String(online) });
  if (cursor) params.set("cursor", cursor);
  return request<SearchPage>(`/api/catalog/unified-search?${params}`, { signal });
}
export function catalogCredits(kind: "person" | "company", id: number, cursor?: string, enrich = false) {
  const params = new URLSearchParams({ enrich: String(enrich && kind === "person") });
  if (cursor) params.set("cursor", cursor);
  return request<SearchPage>(`/api/catalog/${kind}/${id}/credits?${params}`);
}

export type FeedSurface = "home" | "movies" | "series";
export type FeedItem = import("./types").CatalogItem & {
  key: string;
  new_season?: number | null;
  resume?: { season_number: number | null; episode_number: number | null; position_seconds: number; action: string } | null;
};
export type FeedShelf = { id: string; title: string; kind: string; personalized: boolean; items: FeedItem[]; genre_id?: number | null; genre_scope?: "all" | "movie" | "tv" | null };
export type FeedPage = { snapshot_id: string; surface: FeedSurface; personalized: boolean; shelves: FeedShelf[]; next_cursor: string | null; warnings: string[] };
export function getFeed(profileId: number, surface: FeedSurface, cursor?: string) {
  const params = new URLSearchParams({ batch_size: "5" });
  if (cursor) params.set("cursor", cursor);
  return request<FeedPage>(`/api/feeds/profiles/${profileId}/${surface}?${params}`);
}
export function getFeedDiagnostics(profileId: number, snapshot: string) {
  return request<unknown>(`/api/feeds/profiles/${profileId}/diagnostics/${snapshot}`);
}

export type GenrePage = { genre_id: number; title: string; scope: "all" | "movie" | "tv"; results: FeedItem[]; next_cursor: string | null };
export function getGenreItems(genreId: number, scope: "all" | "movie" | "tv", cursor?: string) {
  const params = new URLSearchParams({ kind: scope });
  if (cursor) params.set("cursor", cursor);
  return request<GenrePage>(`/api/catalog/genres/${genreId}/items?${params}`);
}

export type ClientCapabilities = {
  hls: boolean; dash: boolean; video_codecs: string[] | null; audio_codecs: string[] | null;
  max_height: number | null; text_tracks: boolean; subtitle_formats: string[] | null; hdr: boolean | null;
};
export type ClientSessionView = {
  id: string; profile_id: number; display_name: string; client_type: string; state: string;
  capabilities: ClientCapabilities | null; last_seen: string; current_playback: { content_key: string } | null;
  position_seconds: number; revoked_at: string | null;
};
export function detectCapabilities(): ClientCapabilities {
  const video = document.createElement("video");
  const supports = (mime: string) => Boolean(video.canPlayType(mime)) || (typeof MediaSource !== "undefined" && MediaSource.isTypeSupported(mime));
  return {
    hls: supports('application/vnd.apple.mpegurl') || typeof MediaSource !== "undefined", dash: typeof MediaSource !== "undefined",
    video_codecs: [["h264", 'video/mp4; codecs="avc1.42E01E"'], ["hevc", 'video/mp4; codecs="hvc1.1.6.L93.B0"'], ["av1", 'video/mp4; codecs="av01.0.04M.08"'], ["vp9", 'video/webm; codecs="vp9"']].filter(([, mime]) => supports(mime)).map(([name]) => name),
    audio_codecs: [["aac", 'audio/mp4; codecs="mp4a.40.2"'], ["ac3", 'audio/mp4; codecs="ac-3"'], ["eac3", 'audio/mp4; codecs="ec-3"'], ["opus", 'audio/webm; codecs="opus"']].filter(([, mime]) => supports(mime)).map(([name]) => name),
    max_height: Number(sessionStorage.getItem("orbis.client-height")) || 1080,
    text_tracks: true, subtitle_formats: ["vtt", "srt", "ttml"], hdr: matchMedia("(dynamic-range: high)").matches ? true : null,
  };
}
let creatingClient: Promise<ClientSessionView> | null = null;
export async function ensureClientSession(profileId: number): Promise<ClientSessionView> {
  const saved = sessionStorage.getItem("orbis.client-session");
  if (saved) {
    const stored = JSON.parse(saved) as ClientSessionView;
    if (stored.profile_id === profileId) {
      try { return await request<ClientSessionView>(`/api/sessions/${stored.id}`); }
      catch (error) {
        if (!(error instanceof ApiError) || ![403, 404].includes(error.status)) throw error;
        sessionStorage.removeItem("orbis.client-session");
        if (error.status === 403) throw error; // Revocation requires explicit registration, not silent rejoining.
      }
    }
  }
  if (!creatingClient) {
    creatingClient = request<ClientSessionView>("/api/sessions", { method: "POST", body: JSON.stringify({ profile_id: profileId, display_name: "Orbis web browser", client_type: "web", capabilities: detectCapabilities() }) })
      .then(value => { sessionStorage.setItem("orbis.client-session", JSON.stringify(value)); return value; })
      .finally(() => { creatingClient = null; });
  }
  const created = await creatingClient;
  return created.profile_id === profileId ? created : ensureClientSession(profileId);
}
export function heartbeatClient(id: string, state: string, sourceId?: string, position = 0, capabilities?: ClientCapabilities, keepalive = false) {
  return request<ClientSessionView>(`/api/sessions/${id}`, { method: "PATCH", keepalive, body: JSON.stringify({ state, source_session_id: sourceId, position_seconds: position, ...(capabilities ? { capabilities } : {}) }) });
}
export type EpisodeRef = { tmdb_id: number; season_number: number; episode_number: number; title: string | null; aired: boolean };
export type EpisodeLifecycle = {
  current: EpisodeRef; previous: EpisodeRef | null; next: EpisodeRef | null;
  next_status: string; season_transition: boolean; is_final_episode: boolean; autoplay_next: boolean; autoplay_allowed: boolean;
  resume_position_seconds: number; markers: Record<string, number | null>; marker_source: string | null; warning: string | null;
};
export function getEpisodeLifecycle(identity: PlaybackIdentity) {
  return request<EpisodeLifecycle>(`${playbackPath(identity)}/lifecycle?enrich=true`);
}
export function prepareNextEpisode(identity: PlaybackIdentity) {
  return request<PlaybackSession>(`${playbackPath(identity)}/prepare-next`, { method: "POST" });
}
export function transitionEpisode(identity: PlaybackIdentity, direction: "next" | "previous", prepared?: string) {
  return request<PlaybackSession>(`${playbackPath(identity)}/transition`, { method: "POST", body: JSON.stringify({ direction, prepared_source_session_id: prepared }) });
}
