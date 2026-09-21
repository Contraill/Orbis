import type {
  LiveProviderState,
  PlaybackResolution,
  ProviderAdminView,
  ProviderEventView,
  ProviderHealthCheckReport,
  ProviderValidation,
} from "./types";


const PROVIDERS = "/api/admin/providers";
const EDITOR = "/api/admin/provider-editor";


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
