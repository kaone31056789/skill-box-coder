import type {
  Comparison,
  Experiment,
  ExperimentResults,
  Hypothesis,
  ResearchGraph,
  RunDetail,
  SystemStatus,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export function socketUrl(runId: string): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/ws/research-runs/${runId}`;
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the GENESIS API at ${API_URL}. Check that the backend is ` +
        `running and that this origin (${typeof window === "undefined" ? "server" : window.location.origin}) ` +
        `is present in CORS_ORIGINS.`,
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  systemStatus: () => request<SystemStatus>("/system/status"),

  createRun: (body: {
    question: string;
    max_experiments?: number;
    demo_mode?: boolean;
    project_name?: string;
  }) =>
    request<{ id: string }>("/research-runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getRun: (runId: string) => request<RunDetail>(`/research-runs/${runId}`),

  start: (runId: string) =>
    request<RunDetail>(`/research-runs/${runId}/start`, { method: "POST" }),
  pause: (runId: string) =>
    request<RunDetail>(`/research-runs/${runId}/pause`, { method: "POST" }),
  resume: (runId: string) =>
    request<RunDetail>(`/research-runs/${runId}/resume`, { method: "POST" }),
  stop: (runId: string) =>
    request<RunDetail>(`/research-runs/${runId}/stop`, { method: "POST" }),

  graph: (runId: string) => request<ResearchGraph>(`/research-runs/${runId}/graph`),
  comparison: (runId: string) => request<Comparison>(`/research-runs/${runId}/comparison`),
  experiments: (runId: string) => request<Experiment[]>(`/research-runs/${runId}/experiments`),
  hypotheses: (runId: string) => request<Hypothesis[]>(`/research-runs/${runId}/hypotheses`),

  experimentCode: (experimentId: string) =>
    request<{ id: string; name: string; code: string; repair_attempts: number }>(
      `/experiments/${experimentId}/code`,
    ),
  experimentResults: (experimentId: string) =>
    request<ExperimentResults>(`/experiments/${experimentId}/results`),
  runExperiment: (experimentId: string) =>
    request<{ status: string; metrics: Record<string, number>; error: string | null }>(
      `/experiments/${experimentId}/run`,
      { method: "POST" },
    ),

  injectHypothesis: (body: {
    run_id: string;
    title: string;
    description?: string;
    rationale?: string;
    approach?: string;
    feature_set?: string;
  }) =>
    request<Hypothesis>("/hypotheses", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export { ApiError };
