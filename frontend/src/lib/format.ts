// Topic and rubric names are snake_case; keep acronyms and brand casing right ("llm_evaluation" -> "LLM evaluation")
const SPECIAL: Record<string, string> = {
  llm: "LLM", llmops: "LLMOps", rag: "RAG", nlp: "NLP", ml: "ML", mlops: "MLOps", sql: "SQL", hr: "HR",
  api: "API", apis: "APIs", fastapi: "FastAPI", numpy: "NumPy", db: "DB", ai: "AI", genai: "GenAI",
};

export const titleCase = (s: string) =>
  s
    .split("_")
    .map((w, i) => SPECIAL[w.toLowerCase()] ?? (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");

export const interviewTypeLabel = (t: string) =>
  ({ technical: "Technical", system_design: "System design", behavioral: "Behavioral", hr: "HR" })[t] ?? titleCase(t);

export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatDate(iso: string, withTime = false): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  });
}

/** Signed change for stat tiles: "+12", "-3", "0". */
export const signed = (n: number) => (n > 0 ? `+${n}` : String(n));
