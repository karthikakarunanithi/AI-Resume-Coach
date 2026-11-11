import type { FinalReport, SessionSummary } from "./types";

const TOKEN_KEY = "coach_token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable (private mode): the session just won't survive a reload
  }
}

type ValidationIssue = { loc?: (string | number)[]; msg?: string };

const FIELD_LABEL: Record<string, string> = { raw_text: "Job description", role: "Job title", email: "Email", password: "Password" };

/** FastAPI sends a string for handled errors and a list of issues for invalid input (HTTP 422). */
export function errorMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail) || detail.length === 0) return null;
  return (detail as ValidationIssue[])
    .map((issue) => {
      const field = issue.loc?.filter((p) => p !== "body").at(-1);
      const label = typeof field === "string" ? FIELD_LABEL[field] ?? field.replace(/_/g, " ") : null;
      // pydantic prefixes custom errors with "Value error, "; the email checker explains at length after a colon
      const msg = (issue.msg ?? "is invalid").replace(/^Value error, /, "").replace(/^value is not a valid email address:.*/i, "is not a valid email address");
      return label ? `${label}: ${msg}` : msg;
    })
    .join(". ");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<{ status: number; body: T }> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    throw new ApiError(res.status, errorMessage(body?.detail) ?? res.statusText);
  }
  return { status: res.status, body: body as T };
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams({ username: email, password });
  const { body } = await request<{ access_token: string }>("/auth/jwt/login", { method: "POST", body: form });
  setToken(body.access_token);
}

export async function register(email: string, password: string, name: string) {
  await request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name: name || null }),
  });
}

export async function listSessions(): Promise<SessionSummary[]> {
  return (await request<SessionSummary[]>("/sessions")).body;
}

/** Returns null while the interview is still running or the report is being generated (HTTP 202). */
export async function getReport(sessionId: string): Promise<FinalReport | null> {
  const { status, body } = await request<FinalReport>(`/sessions/${sessionId}/report`);
  return status === 202 ? null : body;
}

export async function getSampleReport(): Promise<FinalReport> {
  return (await request<FinalReport>("/sample-report.json")).body;
}

export interface TurnOut {
  session_id: string;
  spoken: string[];
  question_id: string | null;
  done: boolean;
}

export interface SessionCreate {
  role: string;
  interview_type: "technical" | "behavioral" | "hr" | "system_design";
  difficulty: "easy" | "medium" | "hard";
  duration_min: number;
  company_type?: string;
  resume_id?: string;
  jd_id?: string;
}

export async function createSession(body: SessionCreate): Promise<TurnOut> {
  return (
    await request<TurnOut>("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  ).body;
}

export async function uploadResume(file: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("file", file);
  return (await request<{ id: string }>("/resumes", { method: "POST", body: form })).body;
}

export async function createJobDescription(rawText: string): Promise<{ id: string }> {
  return (
    await request<{ id: string }>("/job-descriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_text: rawText }),
    })
  ).body;
}

/** WebSocket URL for a live voice interview (token in the query string: browsers can't set WS headers). */
export function interviewSocketUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/sessions/${sessionId}?token=${encodeURIComponent(getToken() ?? "")}`;
}

export interface Progress {
  interviews: number;
  avg_score: number | null;
  best_score: number | null;
  last_score: number | null;
  change_vs_previous: number | null;
  points: { session_id: string; created_at: string; role: string; interview_type: string; overall_score: number; hiring_signal: string }[];
  weakest_topics: { topic: string; avg_score: number; questions: number }[];
  dimension_averages: Record<string, number>;
}

export async function getProgress(): Promise<Progress> {
  return (await request<Progress>("/users/me/progress")).body;
}

export interface ResumeSummary {
  id: string;
  created_at: string;
  parsed_profile: { name: string | null; skills: string[]; projects: { title: string }[] };
}

export async function listResumes(): Promise<ResumeSummary[]> {
  return (await request<ResumeSummary[]>("/resumes")).body;
}
