/**
 * Records the demo video against the real app (free Groq models): explainer slides + a real interview + report.
 *   REAL_DEMO=1 npx playwright test e2e/demo-video.spec.ts --project=desktop
 * Output: ../demo/raw.webm and ../demo/markers.json (then scripts/make_demo_video.py turns them into MP4 + GIF).
 * Needs the backend (:8000, MODEL_PROFILE=free) and the dev server (:5173).
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { architectureSlide, closingSlide, engineeringSlide, problemSlide, resultsSlide, titleSlide } from "./demo/slides";

test.skip(process.env.REAL_DEMO !== "1", "set REAL_DEMO=1 to record the demo video");
test.setTimeout(16 * 60_000);
test.use({ viewport: { width: 1280, height: 720 }, video: { mode: "on", size: { width: 1280, height: 720 } } });

const API = "http://127.0.0.1:8000";
const OUT = "../demo";
const RESUME = "e2e/fixtures/sample-resume.pdf";
const JD = readFileSync("e2e/fixtures/sample-jd.txt", "utf-8");
const ENV = Object.fromEntries(
  readFileSync("../.env", "utf-8").split(/\r?\n/).filter((l) => /^\w+=/.test(l)).map((l) => [l.split("=")[0], l.slice(l.indexOf("=") + 1).trim()]),
);
const CANDIDATE = `Priya Sharma, GenAI developer, 1.5 years. Built a RAG support bot over 12,000 help articles (recall@5 0.71 -> 0.83 by
tuning chunk size; p95 latency 2.4 s -> 900 ms with Redis caching and streaming), an LLM-as-judge eval set of 200 questions run in CI,
a LangGraph document-QA agent with pgvector that retries with a rewritten query, and a CNN+LSTM deepfake detector (94%).`;

/** Writes the candidate's answer with a free model, in character. The video captions say answers are scripted. */
async function answerFor(question: string, words = "50-70"): Promise<string> {
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${ENV.GROQ_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "openai/gpt-oss-20b", reasoning_effort: "low", max_tokens: 600,
      messages: [
        { role: "system", content: `You are this interview candidate: ${CANDIDATE}\nAnswer in first person, spoken style, ${words} words, specific and honest. No preamble.` },
        { role: "user", content: question },
      ],
    }),
  });
  const body = await res.json();
  return (body.choices?.[0]?.message?.content ?? "I'd approach it step by step, starting with the requirements.").trim();
}

async function api(path: string, init: RequestInit & { token?: string } = {}) {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init.token ? { Authorization: `Bearer ${init.token}` } : {}), ...(init.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

/** A real earlier practice session (not recorded), so the dashboard has a trend to show. */
async function practiceSession(email: string, password: string) {
  await api("/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password, name: "Priya (demo)" }) });
  const { access_token: token } = await api("/auth/jwt/login", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ username: email, password }),
  });
  const form = new FormData();
  form.append("file", new Blob([readFileSync(RESUME)], { type: "application/pdf" }), "resume.pdf");
  const resume = await api("/resumes", { method: "POST", body: form, token });
  let turn = await api("/sessions", {
    method: "POST", token, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role: "GenAI Developer", interview_type: "technical", difficulty: "easy", duration_min: 5, resume_id: resume.id }),
  });
  for (let i = 0; i < 2 && !turn.done; i++) { // short: it only has to give the dashboard a first data point
    const brief = await answerFor(turn.spoken.at(-1) ?? "Tell me about yourself", "12-20"); // a first, shorter attempt
    turn = await api(`/sessions/${turn.session_id}/answers`, {
      method: "POST", token, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: brief }),
    });
    await new Promise((r) => setTimeout(r, 4000)); // human-ish pace keeps the free tier's per-minute token cap happy
  }
  if (!turn.done) {
    // Follow-ups can make an interview longer than our answers: end it so a report is always produced
    turn = await api(`/sessions/${turn.session_id}/end`, { method: "POST", token });
  }
  for (let i = 0; i < 40; i++) {
    const r = await fetch(`${API}/sessions/${turn.session_id}/report`, { headers: { Authorization: `Bearer ${token}` } });
    if (r.status === 200) return;
    await new Promise((res) => setTimeout(res, 3000));
  }
  throw new Error("practice session report never arrived");
}

async function overlay(page: Page) {
  await page.addInitScript(() => {
    const install = () => {
      if (document.getElementById("demo-caption")) return;
      const cap = document.createElement("div");
      cap.id = "demo-caption";
      // Top of the frame, over the header (least informative area), and never in the way of a click
      cap.style.cssText = "position:fixed;left:50%;top:7px;transform:translateX(-50%);max-width:1100px;z-index:99999;pointer-events:none;" +
        "background:rgba(11,11,11,.88);color:#fff;font:500 19px 'Segoe UI',system-ui,sans-serif;padding:9px 20px;border-radius:12px;" +
        "box-shadow:0 6px 24px rgba(0,0,0,.25);transition:opacity .3s;opacity:0;text-align:center;line-height:1.35";
      const cur = document.createElement("div");
      cur.id = "demo-cursor";
      cur.style.cssText = "position:fixed;left:640px;top:360px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:100000;" +
        "background:rgba(42,120,214,.35);border:2px solid #1c5cab;transition:left .45s ease,top .45s ease,transform .15s;pointer-events:none";
      document.body.append(cap, cur);
    };
    // @ts-expect-error demo-only globals
    window.__caption = (text: string) => { install(); const c = document.getElementById("demo-caption")!; c.textContent = text; c.style.opacity = text ? "1" : "0"; };
    // @ts-expect-error demo-only globals
    window.__cursor = (x: number, y: number, press = false) => {
      install(); const c = document.getElementById("demo-cursor")!; c.style.left = `${x}px`; c.style.top = `${y}px`;
      if (press) { c.style.transform = "scale(.7)"; setTimeout(() => (c.style.transform = ""), 180); }
    };
    document.addEventListener("DOMContentLoaded", install);
  });
}

const stamp = Date.now();
const email = `demo-${stamp}@example.com`;
const password = `demo-pass-${stamp}`;

// Before the page exists: video recording starts with the page, so the practice run mustn't be inside the test
test.beforeAll(async () => {
  test.setTimeout(6 * 60_000);
  await practiceSession(email, password);
});

test("record demo video", async ({ page }) => {

  const t0 = Date.now();
  const markers: Record<string, number> = {};
  const mark = (name: string) => (markers[name] = (Date.now() - t0) / 1000);
  const caption = (text: string) => page.evaluate((t) => (window as unknown as { __caption: (s: string) => void }).__caption(t), text);
  const pause = (ms: number) => page.waitForTimeout(ms);
  const point = async (loc: Locator, press = false) => {
    await loc.scrollIntoViewIfNeeded();
    const b = await loc.boundingBox();
    if (b) await page.evaluate(([x, y, p]) => (window as unknown as { __cursor: (x: number, y: number, p: boolean) => void }).__cursor(x, y, p), [b.x + b.width / 2, b.y + b.height / 2, press] as const);
    await pause(press ? 250 : 550);
  };
  const click = async (loc: Locator) => { await point(loc); await point(loc, true); await loc.click(); };
  const slide = async (html: string, ms: number) => { await page.setContent(html); await pause(ms); };
  // After a slide the tab still has the app's URL, so a hash-only goto wouldn't reload the app: start fresh
  const openApp = async (hash: string) => { await page.goto("about:blank"); await page.goto(`http://localhost:5173/${hash}`); };
  await overlay(page);

  // 1. Story
  mark("title");
  await slide(titleSlide, 6000);
  await slide(problemSlide, 8000);

  // 2. Log in and set up an interview
  mark("app");
  await openApp("#/");
  await caption("The app: React front end, FastAPI back end");
  await pause(2500);
  await click(page.getByRole("link", { name: "Log in" }).first());
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await click(page.getByRole("button", { name: "Log in" }));
  await expect(page.getByText("Interviews scored")).toBeVisible({ timeout: 15_000 });
  await caption("Dashboard after one earlier practice session");
  await pause(3000);

  await click(page.getByRole("link", { name: "New interview" }));
  await caption("Set up: role, interview type, difficulty, length");
  await page.getByLabel("Job title").fill("");
  await page.getByLabel("Job title").pressSequentially("GenAI Developer", { delay: 40 });
  await click(page.getByRole("radio", { name: "Medium" }));
  await click(page.getByRole("radio", { name: "10 min" }));
  await caption("Her resume and the job post ground the questions");
  await click(page.getByText("Upload a resume (PDF or DOCX)"));
  await page.locator('input[type="file"]').setInputFiles(RESUME);
  await page.getByPlaceholder(/Paste the job post/).fill(JD);
  await pause(1200);
  await caption("Answers can be spoken (mic + live speech-to-text) or typed; typed here");
  await click(page.getByRole("radio", { name: "Type" }));
  await pause(1500);
  mark("start");
  await click(page.getByRole("button", { name: "Start interview" }));
  await caption("Parsing the resume and job post, then a LangGraph planner picks the questions…");
  await expect(page.getByText(/Question 1 of \d+/)).toBeVisible({ timeout: 120_000 });

  // 3. The interview
  mark("interview");
  const answer = page.getByLabel("Your answer");
  const reportLink = page.getByRole("link", { name: "See your feedback report" });
  const notes = [
    "Question 1 is about a project on her own resume",
    "If an answer lacks detail, Asha asks a follow-up (rules allow at most 2)",
    "The next question targets a skill the job post requires",
    "Each answer is scored in the background, so the conversation never waits",
    "Asha's reply streams in; each sentence is spoken as soon as it's complete",
    "Questions also come from a 543-question bank, found by hybrid search",
  ];
  const MAX_ANSWERS = 5; // keeps the video short; then we end early, which shows that feature too
  for (let turn = 0; turn < MAX_ANSWERS; turn++) {
    const state = await Promise.race([
      expect(answer).toBeEnabled({ timeout: 90_000 }).then(() => "answer" as const),
      reportLink.waitFor({ timeout: 90_000 }).then(() => "done" as const),
    ]);
    if (state === "done") break;
    const asked = await page.locator('[aria-label="Conversation"] p').last().innerText();
    await caption(notes[turn]);
    await pause(2600);
    const text = await answerFor(asked);
    await caption("For this demo, a script types the candidate's answers");
    await click(answer);
    await answer.pressSequentially(text, { delay: 8 });
    await click(page.getByRole("button", { name: "Send" }));
  }
  if (!(await reportLink.isVisible())) {
    await expect(answer).toBeEnabled({ timeout: 90_000 });
    await caption("Ending early: the report will cover the questions answered so far");
    await click(page.getByRole("button", { name: "End interview", exact: true }));
    await pause(1800);
    await click(page.getByRole("button", { name: "Yes, end interview" }));
  }
  await expect(reportLink).toBeVisible({ timeout: 90_000 });
  await caption("Interview finished. The coach agent is writing the report…");
  await pause(2500);
  const reportUrl = await reportLink.getAttribute("href");

  // 4. How it works, while the report is generated
  mark("slides");
  await slide(architectureSlide, 9000);
  await slide(engineeringSlide, 9000);

  // 5. The report
  mark("report");
  await openApp(reportUrl ?? "#/");
  await expect(page.getByText(/\/100/).first()).toBeVisible({ timeout: 120_000 });
  await caption("Overall score and hiring signal, computed in code from the rubric");
  await pause(3500);
  const scroll = async (px: number, ms: number) => { await page.mouse.wheel(0, px); await pause(ms); };
  await caption("Rubric scores, strengths and focus areas");
  await scroll(420, 3500);
  await caption("A 7-day practice plan targeting what she missed");
  await scroll(520, 3500);
  await caption("Every score quotes her actual words; no quote, no credit");
  await scroll(520, 4000);
  const stronger = page.getByRole("button", { name: "Show a stronger answer" }).first();
  if (await stronger.isVisible().catch(() => false)) {
    await caption("Plus a stronger sample answer for her weakest questions");
    await click(stronger);
    await pause(3500);
  }

  // 6. Progress
  mark("dashboard");
  await openApp("#/");
  await expect(page.getByText("Interviews scored")).toBeVisible();
  await caption("Progress across sessions: score trend and weakest topics");
  await pause(7000);
  await caption("");

  // 7. Results + close
  mark("results");
  await slide(resultsSlide, 9000);
  await slide(closingSlide, 6000);
  mark("end");

  mkdirSync(OUT, { recursive: true });
  writeFileSync(`${OUT}/markers.json`, JSON.stringify(markers, null, 2));
  await page.close();
  await page.video()!.saveAs(`${OUT}/raw.webm`);
  writeFileSync(`${OUT}/demo-account.txt`, `${email}\n`); // so the demo user can be cleaned up
});
