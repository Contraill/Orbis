import type {
  CatalogDetails,
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

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let detail: unknown = null;

    try {
      const body = await response.json();
      detail = body.detail;

      if (typeof body.detail === "string") {
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

    throw new ApiError(
      response.status,
      message,
      detail,
    );
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
const library = (id: number) => `/api/library/profiles/${id}`;
export const getContinue = (id: number, kind = "all") => request<ContinueEntry[]>(`${library(id)}/continue?kind=${kind}`);
export const hideContinue = (id: number, item: ContentSelection) => request(`${library(id)}/continue/hide`, { method: "POST", body: JSON.stringify(item) });
export const getMyList = (id: number, kind = "all") => request<LibraryItem[]>(`${library(id)}/my-list?kind=${kind}`);
export const getHistory = (id: number) => request<HistoryEntry[]>(`${library(id)}/history`);
export const setListIntent = (id: number, item: ContentSelection, enabled: boolean, negative = false) => request(`${library(id)}/${negative ? "not-interested" : "my-list"}`, { method: "PUT", body: JSON.stringify({ ...item, enabled }) });
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

  return request<PlaybackResolutionSummary>(url, {
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

  return request<PlaybackResolutionSummary>(url, {
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


export function getProviderSettings(
  providerId: string,
) {
  return request<Record<string, unknown>>(
    `${EDITOR}/${providerId}/settings`,
  );
}


export function saveProviderSettings(
  providerId: string,
  settings: Record<string, unknown>,
) {
  return request<Record<string, unknown>>(
    `${EDITOR}/${providerId}/settings`,
    {
      method: "PUT",
      body: JSON.stringify({ settings }),
    },
  );
}
