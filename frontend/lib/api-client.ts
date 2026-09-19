/**
 * API client for the EduPath FastAPI backend.
 *
 * ARCHITECTURE_CONTRACTS.md §8: REST + SSE under `/api/...`. This client is a
 * thin typed fetch wrapper; it does not know about any specific endpoint's
 * business shape yet (those land with the phase that builds them). It exists
 * now so later phases have one place to add typed calls and one error
 * convention (`ApiError`) shared across the app.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown };

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, ...rest } = options;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let code = "unknown_error";
    let message = `Request to ${path} failed with status ${response.status}`;
    try {
      const errorBody = await response.json();
      code = errorBody?.error?.code ?? code;
      message = errorBody?.error?.message ?? message;
    } catch {
      // Response wasn't JSON; keep the generic message above.
    }
    throw new ApiError(response.status, code, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  database: { ok: boolean; error: string | null };
  orchestration: { ok: boolean; error: string | null };
}

export const apiClient = {
  getHealth: () => request<HealthStatus>("/api/health"),

  /** Opens the SSE trace stream for a run. Callers own the EventSource lifecycle. */
  runEventsUrl: (runId: string) => `${API_BASE_URL}/api/runs/${runId}/events`,
};
