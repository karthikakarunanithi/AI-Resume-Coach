/**
 * Real end-to-end run: real backend, real LLMs, real database. Costs API credits, so it only runs when asked:
 *   REAL_E2E=1 npx playwright test e2e/real-interview.spec.ts --project=desktop
 * Needs the backend on :8000 (with API keys) and the dev server on :5173.
 */
import { expect, test, type Page } from "@playwright/test";

test.skip(process.env.REAL_E2E !== "1", "set REAL_E2E=1 to run against the real backend");
test.setTimeout(8 * 60_000);

const ANSWERS = [
  "In my RAG support bot I compared 256, 512 and 1024 token chunks with 50 tokens of overlap. I measured recall at 5 on a labelled set of 120 tickets: 512 gave 0.83 against 0.71 for 256, and 1024 doubled prompt tokens without better recall, so we chose 512.",
  "I'd keep a versioned golden set of real questions with reference answers, measure retrieval with recall at k and generation with faithfulness using an LLM judge validated against my own ratings, and run it in CI so a prompt change that drops either metric fails the build.",
  "In LangGraph the state is a typed dict; each node returns only the keys it changes, list fields use an add reducer, and a conditional edge after the tool node retries with a rewritten query up to three times before falling back. A checkpointer lets a crashed run resume.",
  "I'm not completely sure, but I think I would start by checking the logs and the latency of each step.",
];

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 400 && !r.url().includes("/@vite")) problems.push(`HTTP ${r.status()} ${r.request().method()} ${r.url()}`);
  });
  page.on("websocket", (ws) => {
    ws.on("framereceived", (f) => {
      const msg = typeof f.payload === "string" ? f.payload : "";
      if (msg.includes('"type": "error"') || msg.includes('"type":"error"')) problems.push(`ws error: ${msg}`);
    });
    ws.on("close", () => console.log("WS closed"));
  });
  return problems;
}

test("real interview: sign up, upload resume + JD, typed answers, report", async ({ page }) => {
  const problems = watch(page);
  const shot = (name: string) => page.screenshot({ path: `e2e/screenshots/real-${name}.png`, fullPage: true });
  const stamp = Date.now();

  // Sign up a throwaway test account on the local dev server
  await page.goto("/#/login?signup");
  await page.getByLabel("Name").fill("E2E Test");
  await page.getByLabel("Email").fill(`e2e-${stamp}@example.com`);
  await page.getByLabel("Password").fill(`e2e-pass-${stamp}`);
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: /first mock interview/ })).toBeVisible({ timeout: 15_000 });

  // Setup: role, easy, 5 minutes, upload resume, paste JD, type mode
  await page.goto("/#/interview");
  await page.getByLabel("Job title").fill("GenAI Developer");
  await page.getByRole("radio", { name: "Easy" }).click();
  await page.getByRole("radio", { name: "5 min" }).click();
  await page.getByText("Upload a resume (PDF or DOCX)").click();
  await page.locator('input[type="file"]').setInputFiles("e2e/fixtures/sample-resume.pdf");
  const { readFileSync } = await import("node:fs");
  await page.getByPlaceholder(/Paste the job post/).fill(readFileSync("e2e/fixtures/sample-jd.txt", "utf-8"));
  await page.getByRole("radio", { name: "Type" }).click();
  await shot("1-setup");

  const t0 = Date.now();
  await page.getByRole("button", { name: "Start interview" }).click();
  const started = await Promise.race([
    page.getByText(/Question 1 of \d+/).waitFor({ timeout: 120_000 }).then(() => true),
    page.getByRole("alert").waitFor({ timeout: 120_000 }).then(() => false),
  ]);
  if (!started) {
    const shown = await page.getByRole("alert").innerText();
    console.log(`Setup failed after ${((Date.now() - t0) / 1000).toFixed(1)} s. The page shows: "${shown}"`);
    console.log(`PROBLEMS (${problems.length}):\n` + problems.join("\n"));
    await shot("setup-error");
    throw new Error(`Interview could not start: ${shown}`);
  }
  console.log(`Planning (resume parse + JD + plan + opening): ${((Date.now() - t0) / 1000).toFixed(1)} s`);

  const answer = page.getByLabel("Your answer");
  const reportLink = page.getByRole("link", { name: "See your feedback report" });
  for (let turn = 0; turn < 12; turn++) {
    const ready = await Promise.race([
      answer.waitFor({ state: "visible" }).then(() => expect(answer).toBeEnabled({ timeout: 90_000 })).then(() => "answer" as const),
      reportLink.waitFor({ timeout: 90_000 }).then(() => "done" as const),
    ]);
    if (ready === "done") break;
    const bubbles = page.locator('[aria-label="Conversation"] p');
    const asked = await bubbles.last().innerText();
    const progress = await page.getByText(/Question \d+ of \d+/).innerText().catch(() => "?");
    console.log(`\n[${progress}] ASHA: ${asked}`);
    if (turn === 0) await shot("2-room");
    const text = ANSWERS[turn % ANSWERS.length];
    console.log(`YOU: ${text.slice(0, 90)}...`);
    const sent = Date.now();
    await answer.fill(text);
    await page.getByRole("button", { name: "Send" }).click();
    await Promise.race([
      expect(answer).toBeEnabled({ timeout: 90_000 }),
      reportLink.waitFor({ timeout: 90_000 }),
    ]);
    console.log(`  turn latency (send -> can answer again): ${((Date.now() - sent) / 1000).toFixed(1)} s`);
  }
  await expect(reportLink).toBeVisible();
  await shot("3-ended");

  const tr = Date.now();
  await reportLink.click();
  await expect(page.getByText(/\/100/).first()).toBeVisible({ timeout: 180_000 });
  console.log(`\nReport ready after ${((Date.now() - tr) / 1000).toFixed(1)} s`);
  await shot("4-report");
  console.log("REPORT TEXT:\n" + (await page.locator("main").innerText()).slice(0, 2500));

  console.log(`\nPROBLEMS (${problems.length}):\n` + problems.join("\n"));
});
