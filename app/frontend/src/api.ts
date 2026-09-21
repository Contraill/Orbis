import type {
  LiveProviderState,
  PlaybackFailoverRequest,
  PlaybackIdentity,
  PlaybackResolution,
  PlaybackSession,
  PlaybackState,
  PlaybackStateUpdate,
  ProviderAdminView,
  ProviderEventView,
  ProviderHealthCheckReport,
  ProviderValidation,
} from "./types";


const PROVIDERS = "/api/admin/providers";
const EDITOR = "/api/admin/provider-editor";


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


async function request<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);

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

  return response.json() as Promise<T>;
}


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

  return request<PlaybackResolution>(url, {
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

  return request<PlaybackResolution>(url, {
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
