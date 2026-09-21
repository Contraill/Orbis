import type {
  PlaybackResolution,
  ProviderAdminView,
  ProviderEventView,
  ProviderHealthCheckReport,
} from "./types";


const BASE = "/api/admin/providers";


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
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BASE}${path}`, {
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
      // Keep HTTP status as the fallback error.
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
  return request<ProviderAdminView[]>("");
}


export function updateProvider(
  providerId: string,
  payload: {
    enabled?: boolean;
    priority?: number;
  },
) {
  return request<ProviderAdminView>(`/${providerId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}


export function testProvider(providerId: string) {
  return request<ProviderHealthCheckReport>(
    `/${providerId}/test`,
    {
      method: "POST",
    },
  );
}


export function getProviderLogs(
  providerId: string,
  limit = 30,
) {
  return request<ProviderEventView[]>(
    `/${providerId}/logs?limit=${limit}`,
  );
}


export function resolveMovie(
  tmdbId: number,
  providerId?: string,
) {
  const path = providerId
    ? `/${providerId}/resolve-test/movie/${tmdbId}`
    : `/resolve-test/movie/${tmdbId}`;

  return request<PlaybackResolution>(path, {
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

  const path = providerId
    ? `/${providerId}/resolve-test/${suffix}`
    : `/resolve-test/${suffix}`;

  return request<PlaybackResolution>(path, {
    method: "POST",
  });
}
