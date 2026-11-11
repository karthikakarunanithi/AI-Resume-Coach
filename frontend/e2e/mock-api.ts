import type { Page, WebSocketRoute } from "@playwright/test";
import { readFileSync } from "node:fs";

export const sampleReport = JSON.parse(readFileSync(new URL("../public/sample-report.json", import.meta.url), "utf-8"));

export const progress = {
  interviews: 5,
  avg_score: 61,
  best_score: 74,
  last_score: 74,
  change_vs_previous: 9,
  points: [48, 55, 63, 65, 74].map((score, i) => ({
    session_id: `s${i}`,
    created_at: new Date(Date.UTC(2026, 9, 3 + i * 6)).toISOString(),
    role: i % 2 ? "ML Engineer" : "GenAI Developer",
    interview_type: i === 3 ? "behavioral" : "technical",
    overall_score: score,
    hiring_signal: score >= 65 ? "Lean yes" : "Lean no",
  })),
  weakest_topics: [
    { topic: "llm_evaluation", avg_score: 41, questions: 4 },
    { topic: "system_design", avg_score: 52, questions: 2 },
    { topic: "rag", avg_score: 63, questions: 5 },
    { topic: "deep_learning", avg_score: 70, questions: 3 },
  ],
  dimension_averages: { correctness: 3.6, depth: 2.8 },
};

export const sessions = progress.points
  .map((p, i) => ({ id: p.session_id, role: p.role, interview_type: p.interview_type, difficulty: "medium", status: "done", created_at: p.created_at, overall_score: p.overall_score, hiring_signal: p.hiring_signal }))
  .reverse()
  .concat([]);

/** Log in (token in localStorage), mock the REST API, and make speech synthesis finish instantly. */
export async function mockApi(page: Page, opts: { empty?: boolean } = {}) {
  await page.addInitScript(() => {
    localStorage.setItem("coach_token", "test-token");
    // Headless Chrome has no voices; finish each utterance right away so the room can move on
    const synth = {
      getVoices: () => [],
      cancel: () => {},
      speak: (u: SpeechSynthesisUtterance) => setTimeout(() => u.onend?.(new Event("end") as SpeechSynthesisEvent), 30),
    };
    Object.defineProperty(window, "speechSynthesis", { value: synth });
  });
  const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/users/me/progress", (r) => r.fulfill(json(opts.empty ? { ...progress, interviews: 0, points: [], weakest_topics: [], avg_score: null, best_score: null, last_score: null, change_vs_previous: null } : progress)));
  await page.route("**/sessions", (r) =>
    r.request().method() === "POST"
      ? r.fulfill(json({ session_id: "live-1", spoken: ["Hi!"], question_id: "q1", done: false }, 201))
      : r.fulfill(json(opts.empty ? [] : sessions)),
  );
  await page.route("**/sessions/*/report", (r) => r.fulfill(json(sampleReport)));
  await page.route("**/resumes", (r) =>
    r.fulfill(json([{ id: "r1", created_at: "2026-10-20T10:00:00Z", parsed_profile: { name: "Karthika K", skills: ["Python", "FastAPI", "LangGraph", "PyTorch"], projects: [] } }])),
  );
}

/** A scripted interviewer on the WebSocket: two questions, typed answers. */
export async function mockInterviewSocket(page: Page): Promise<string[]> {
  const received: string[] = [];
  await page.routeWebSocket(/\/ws\/sessions\//, (ws: WebSocketRoute) => {
    let seq = 0;
    const say = (text: string) => {
      ws.send(JSON.stringify({ type: "ai_text_delta", text }));
      ws.send(JSON.stringify({ type: "ai_sentence", seq: seq++, text }));
    };
    const progress = (n: number, done = false) => ({ question_id: `q${n}`, question_number: n, total_questions: 2, time_left_s: 540, done });
    ws.send(JSON.stringify({ type: "ready", tts: "browser", ...progress(1) }));
    say("Hi Karthika! How did you choose a chunk size for your RAG pipeline?");
    ws.send(JSON.stringify({ type: "turn_end", ...progress(1) }));

    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      received.push(msg.type === "text_answer" ? msg.text : msg.type);
      ws.send(JSON.stringify({ type: "status", state: "thinking" }));
      if (msg.type === "text_answer" && received.length === 1) {
        say("Got it. How would you evaluate a change to that pipeline?");
        ws.send(JSON.stringify({ type: "turn_end", ...progress(2) }));
      } else {
        say("That's all for today. Thank you!");
        ws.send(JSON.stringify({ type: "turn_end", question_id: null, done: true }));
        ws.send(JSON.stringify({ type: "interview_end", session_id: "live-1" }));
      }
    });
  });
  return received;
}
