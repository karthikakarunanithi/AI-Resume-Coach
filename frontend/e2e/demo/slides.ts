/** Explainer slides for the demo video (1280x720), styled like the app. Every number here was measured. */

const BASE = `
  <style>
    * { box-sizing: border-box; margin: 0; }
    body { width: 1280px; height: 720px; font-family: "Segoe UI", system-ui, sans-serif; background: #f9f9f7; color: #0b0b0b;
           display: flex; flex-direction: column; justify-content: center; padding: 64px 88px; }
    .kicker { color: #1c5cab; font-weight: 600; font-size: 20px; letter-spacing: .02em; }
    h1 { font-size: 58px; line-height: 1.1; margin-top: 12px; font-weight: 650; }
    h2 { font-size: 40px; margin-top: 8px; font-weight: 650; }
    p.lead { font-size: 25px; color: #52514e; margin-top: 20px; max-width: 980px; line-height: 1.45; }
    .chips { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 34px; }
    .chip { background: #fcfcfb; border: 1px solid #e1e0d9; border-radius: 999px; padding: 8px 16px; font-size: 18px; color: #52514e; }
    .grid { display: grid; gap: 18px; margin-top: 30px; }
    .card { background: #fcfcfb; border: 1px solid #e1e0d9; border-radius: 18px; padding: 20px 22px; }
    .card b { display: block; font-size: 22px; margin-bottom: 6px; }
    .card span { font-size: 18px; color: #52514e; line-height: 1.4; }
    .num { font-size: 40px; font-weight: 650; color: #0b0b0b; }
    .who { margin-top: 40px; font-size: 22px; color: #52514e; }
    .fade { animation: fade .5s ease-out both; }
    @keyframes fade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  </style>`;

const page = (body: string) => `<!doctype html><html><head><meta charset="utf-8">${BASE}</head><body><div class="fade">${body}</div></body></html>`;

export const titleSlide = page(`
  <div class="kicker">Portfolio project · AI Engineering</div>
  <h1>AI Interview Coach</h1>
  <p class="lead">A voice mock interviewer that plans questions from your resume and the job description, asks follow-ups like a real panel, and scores every answer with evidence.</p>
  <div class="chips">${["Python", "FastAPI", "LangGraph", "LiteLLM", "PostgreSQL + pgvector", "React + TypeScript", "Whisper STT", "Playwright"]
    .map((t) => `<span class="chip">${t}</span>`).join("")}</div>
  <div class="who">Karthika K</div>`);

export const problemSlide = page(`
  <div class="kicker">The problem</div>
  <h2>Practising alone doesn't feel like a real interview</h2>
  <p class="lead">No follow-up questions, no pressure to explain trade-offs, and no honest feedback on why an answer was weak.</p>
  <div class="grid" style="grid-template-columns: repeat(3, 1fr)">
    <div class="card"><b>1 · Upload resume + job post</b><span>Questions come from your own projects and the skills the job asks for.</span></div>
    <div class="card"><b>2 · Talk to Asha</b><span>One question at a time, with follow-ups when an answer is vague. By voice or by typing.</span></div>
    <div class="card"><b>3 · Get a scored report</b><span>Rubric scores backed by quotes from your answers, a stronger sample answer, a 7-day plan.</span></div>
  </div>`);

const box = (title: string, lines: string[], tint = "#fcfcfb") =>
  `<div class="card" style="background:${tint}"><b>${title}</b><span>${lines.join("<br>")}</span></div>`;

export const architectureSlide = page(`
  <div class="kicker">How it works</div>
  <h2>Architecture</h2>
  <div class="grid" style="grid-template-columns: 1fr 1.25fr 1fr; align-items: stretch; margin-top: 24px">
    ${box("Browser", ["React + TypeScript", "Silero VAD detects end of speech", "WebSocket: audio in, streamed reply out", "Sentence-by-sentence speech"])}
    ${box("FastAPI + LangGraph agent", ["Planner: resume + JD + question bank", "Interviewer: streams its reply; rules cap follow-ups", "Guardrail: blocks “give me 10/10”", "Background: evaluator scores each answer", "Coach: final report + 7-day plan"], "#e3eefc")}
    ${box("Data + models", ["PostgreSQL + pgvector", "Hybrid search: vectors + full-text (RRF) over 543 questions", "LiteLLM router: Groq (free) or Claude", "Whisper speech-to-text"])}
  </div>
  <p class="lead" style="font-size:20px; margin-top:22px">Model routing from one config file: a fast model holds the conversation, a stronger one judges the answers.</p>`);

export const engineeringSlide = page(`
  <div class="kicker">Engineering decisions</div>
  <h2>Built to be fair, fast and testable</h2>
  <div class="grid" style="grid-template-columns: repeat(3, 1fr)">
    ${box("Evidence-checked scoring", ["Every score must quote the candidate.", "Quotes are verified in code; no evidence caps it at 2/5."])}
    ${box("Streaming that can't misfire", ["The interviewer's action is validated before a single word is spoken."])}
    ${box("Rules before the LLM", ["Max 2 follow-ups, time-boxed wrap-up; the model only picks among allowed moves."])}
    ${box("Eval harness", ["Adversarial robustness set, consistency runs, latency + cost reports from logged calls."])}
    ${box("Observability", ["Every LLM call logged: tokens, latency, cost, fallbacks, prompt version."])}
    ${box("Tests", ["194 backend · 8 frontend unit · 8 Playwright end-to-end, plus real-API runs."])}
  </div>`);

export const resultsSlide = page(`
  <div class="kicker">Measured, not guessed</div>
  <h2>Results so far</h2>
  <div class="grid" style="grid-template-columns: repeat(3, 1fr)">
    <div class="card"><div class="num">≈1 s</div><span>to the interviewer's first sentence (server-side, real runs; target 2.5 s)</span></div>
    <div class="card"><div class="num">0.13</div><span>score spread across repeat evaluations (target ≤ 0.3)</span></div>
    <div class="card"><div class="num">11 / 13</div><span>adversarial cases handled: prompt injection, rambling, confidently wrong…</span></div>
    <div class="card"><div class="num">9.5% → 4.1%</div><span>speech-to-text word error rate with the resume vocabulary prompt (synthetic speech)</span></div>
    <div class="card"><div class="num">$0</div><span>per interview on the free-tier model profile</span></div>
    <div class="card"><div class="num">Next</div><span>agreement with human raters (Spearman ρ ≥ 0.7) on recorded answers</span></div>
  </div>`);

export const closingSlide = page(`
  <div class="kicker">Thanks for watching</div>
  <h1>AI Interview Coach</h1>
  <p class="lead">Agents, RAG, voice, evaluation and a full-stack app, built end to end.</p>
  <div class="chips"><span class="chip">Code on GitHub: link in the post</span><span class="chip">Open to AI / ML / GenAI engineering roles</span></div>
  <div class="who">Karthika K</div>`);
