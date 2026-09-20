/**
 * API client for the EduPath FastAPI backend.
 *
 * ARCHITECTURE_CONTRACTS.md §8: REST + SSE under `/api/...`, session-cookie
 * identity (`credentials: "include"`). One typed fetch wrapper and one error
 * convention (`ApiError`). Learner identity is never sent by the client: the
 * backend derives it from the session (§7).
 *
 * `runId` opts a call into live tracing: it is sent as `X-Run-Id`, and the
 * backend publishes that request's real trace events onto
 * `GET /api/runs/{runId}/events` (see lib/trace-store.ts).
 */
import type {
  ChatResponse,
  ClaimDecision,
  ConfirmationSummary,
  DecisionRecord,
  DocumentUploadResponse,
  GapReport,
  HealthStatus,
  IntakeRequest,
  LearnerProfile,
  PendingClaim,
  PlanItem,
  PlanRevision,
  PlanRevisionDetail,
  PracticeSet,
  ProgressReport,
  Resource,
  Role,
  Skill,
  SkillDetail,
  SubmitPracticeRequest,
  SubmitPracticeResponse,
  WeeklyPlan,
  Evidence,
} from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** True only when demo mode is explicitly enabled (never implied). */
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** The API could not be reached at all (network down, backend stopped). */
  get isUnreachable() {
    return this.status === 0;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  form?: FormData;
  runId?: string;
}

function messageFromBody(body: unknown, fallback: string): { code: string; message: string } {
  if (body && typeof body === "object") {
    const b = body as { error?: { code?: string; message?: string }; detail?: unknown };
    if (b.error?.message) return { code: b.error.code ?? "error", message: b.error.message };
    if (typeof b.detail === "string") return { code: "error", message: b.detail };
    if (Array.isArray(b.detail) && b.detail[0]?.msg) return { code: "validation_error", message: String(b.detail[0].msg) };
  }
  return { code: "unknown_error", message: fallback };
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, form, runId, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = { ...(headers as Record<string, string> | undefined) };
  if (runId) finalHeaders["X-Run-Id"] = runId;
  if (body !== undefined) finalHeaders["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      credentials: "include",
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "unreachable", "EduPath's API could not be reached.");
  }

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      // not JSON; use the generic message below
    }
    const { code, message } = messageFromBody(parsed, `Request to ${path} failed with status ${response.status}`);
    throw new ApiError(response.status, code, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A 404 from a "get current X" endpoint means "not created yet", not a failure. */
async function orNull<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),

  // Catalog
  roles: () => request<Role[]>("/api/roles"),
  skills: (ids?: string[]) =>
    request<Skill[]>(`/api/catalog/skills${ids?.length ? `?ids=${encodeURIComponent(ids.join(","))}` : ""}`),
  resources: (ids: string[]) => request<Resource[]>(`/api/catalog/resources?ids=${encodeURIComponent(ids.join(","))}`),

  // Learner profile and evidence
  profile: () => orNull(request<LearnerProfile>("/api/learners/me/profile")),
  createProfile: (body: IntakeRequest) => request<LearnerProfile>("/api/learners", { method: "POST", body }),
  uploadDocument: (form: FormData, runId?: string) =>
    request<DocumentUploadResponse>("/api/learners/me/documents", { method: "POST", form, runId }),
  pendingClaims: () => request<PendingClaim[]>("/api/learners/me/claims/pending"),
  confirmClaims: (decisions: ClaimDecision[], runId?: string) =>
    request<ConfirmationSummary>("/api/learners/me/claims/confirm", { method: "POST", body: { decisions }, runId }),
  evidence: () => request<Evidence[]>("/api/learners/me/evidence"),

  // Gaps, skills
  gaps: () => request<GapReport>("/api/learners/me/gaps"),
  skillDetail: (skillId: string) => request<SkillDetail>(`/api/learners/me/skills/${encodeURIComponent(skillId)}`),

  // Plans
  currentPlan: () => orNull(request<WeeklyPlan>("/api/learners/me/plans/current")),
  createPlan: (body: { week_index?: number; dry_run?: boolean; hours?: number }, runId?: string) =>
    request<WeeklyPlan>("/api/learners/me/plans", { method: "POST", body, runId }),
  revisions: async () => (await orNull(request<PlanRevision[]>("/api/learners/me/plans/current/revisions"))) ?? [],
  revisionDetail: (planId: string, revisionId: string) =>
    request<PlanRevisionDetail>(`/api/learners/me/plans/${planId}/revisions/${revisionId}`),
  revertRevision: (planId: string, revisionId: string) =>
    request<WeeklyPlan>(`/api/learners/me/plans/${planId}/revisions/${revisionId}/revert`, { method: "POST" }),
  setItemStatus: (itemId: string, status: PlanItem["status"]) =>
    request<PlanItem>(`/api/learners/me/plans/items/${itemId}`, { method: "PATCH", body: { status } }),

  // Practice
  createPractice: (skillId: string, purpose: string, runId?: string) =>
    request<PracticeSet>("/api/learners/me/practice", { method: "POST", body: { skill_id: skillId, purpose }, runId }),
  submitPractice: (setId: string, body: SubmitPracticeRequest, runId?: string) =>
    request<SubmitPracticeResponse>(`/api/practice/${setId}/submit`, { method: "POST", body, runId }),

  // Progress, tutor, provenance
  progress: () => request<ProgressReport>("/api/learners/me/progress"),
  chat: (message: string, hints?: { skill_id_hint?: string; decision_id_hint?: string }, runId?: string) =>
    request<ChatResponse>("/api/learners/me/chat", { method: "POST", body: { message, ...hints }, runId }),
  decision: (decisionId: string) => request<DecisionRecord>(`/api/decisions/${decisionId}`),

  /** SSE trace stream for a run. Callers own the EventSource lifecycle. */
  runEventsUrl: (runId: string) => `${API_BASE_URL}/api/runs/${runId}/events`,
};

/** Kept for existing callers of the Phase 1 client. */
export const apiClient = {
  getHealth: api.health,
  runEventsUrl: api.runEventsUrl,
};
