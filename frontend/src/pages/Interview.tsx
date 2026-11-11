import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, createJobDescription, createSession, listResumes, uploadResume, type ResumeSummary, type SessionCreate } from "../api";
import { Button, Card, ErrorNote, LinkButton, Segmented } from "../components/ui";
import { formatClock, formatDate } from "../lib/format";
import { useMicLevel } from "../voice/useMicLevel";
import { useVoiceInterview, type Phase } from "../voice/useVoiceInterview";

type Mode = "voice" | "text";

export default function Interview({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [started, setStarted] = useState<{ id: string; mode: Mode } | null>(null);
  return started ? <Room sessionId={started.id} voice={started.mode === "voice"} /> : <Setup onStarted={(id, mode) => setStarted({ id, mode })} onUnauthorized={onUnauthorized} />;
}

const TYPES: { value: SessionCreate["interview_type"]; label: string; hint: string }[] = [
  { value: "technical", label: "Technical", hint: "Concepts, your projects, the JD's skills" },
  { value: "system_design", label: "System design", hint: "Design a system out loud, trade-offs" },
  { value: "behavioral", label: "Behavioral", hint: "STAR stories about real situations" },
  { value: "hr", label: "HR", hint: "Motivation, goals, fit" },
];

function Setup({ onStarted, onUnauthorized }: { onStarted: (id: string, mode: Mode) => void; onUnauthorized: () => void }) {
  const [form, setForm] = useState<SessionCreate>({ role: "GenAI Developer", interview_type: "technical", difficulty: "medium", duration_min: 10 });
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [resumeChoice, setResumeChoice] = useState<string>("none"); // resume id, "new" or "none"
  const [file, setFile] = useState<File | null>(null);
  const [jd, setJd] = useState("");
  const [mode, setMode] = useState<Mode>("voice");
  const [testingMic, setTestingMic] = useState(false);
  const mic = useMicLevel(testingMic);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listResumes()
      .then((rs) => {
        setResumes(rs);
        setResumeChoice(rs.length ? rs[0].id : "new");
      })
      .catch((e) => e instanceof ApiError && e.status === 401 && onUnauthorized());
  }, [onUnauthorized]);

  const set = <K extends keyof SessionCreate>(k: K, v: SessionCreate[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function start(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setTestingMic(false);
    try {
      const body = { ...form };
      if (resumeChoice === "new" && file) {
        setStatus("Reading your resume...");
        body.resume_id = (await uploadResume(file)).id;
      } else if (resumeChoice !== "new" && resumeChoice !== "none") {
        body.resume_id = resumeChoice;
      }
      if (jd.trim()) {
        setStatus("Analyzing the job description...");
        body.jd_id = (await createJobDescription(jd)).id;
      }
      setStatus("Planning your questions...");
      onStarted((await createSession(body)).session_id, mode);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
      setStatus(null);
    }
  }

  const field = "mt-1 w-full rounded-lg bg-surface px-3 py-2 text-ink ring-1 ring-ring focus:outline-none focus:ring-2 focus:ring-accent";
  const jdTooShort = jd.trim().length > 0 && jd.trim().length < 50;
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">New mock interview</h1>
      <p className="mt-1 text-ink-2">Questions are planned from your resume and the job description, so add them if you can.</p>

      <form onSubmit={start} className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-6">
          <Card title="The role">
            <label className="block text-sm">
              Job title
              <input className={field} required minLength={2} value={form.role} onChange={(e) => set("role", e.target.value)} placeholder="e.g. ML Engineer" />
            </label>
            <fieldset className="mt-4">
              <legend className="text-sm">Interview type</legend>
              <div className="mt-1 grid gap-2 sm:grid-cols-2">
                {TYPES.map((t) => (
                  <label key={t.value} className={`flex cursor-pointer flex-col rounded-xl p-3 ring-1 transition-colors ${form.interview_type === t.value ? "bg-accent-wash ring-accent" : "ring-ring hover:bg-wash"}`}>
                    <input type="radio" name="type" className="sr-only" checked={form.interview_type === t.value} onChange={() => set("interview_type", t.value)} />
                    <span className="text-sm font-medium">{t.label}</span>
                    <span className="text-xs text-ink-2">{t.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-4 flex flex-wrap gap-6">
              <div>
                <p className="mb-1 text-sm">Difficulty</p>
                <Segmented label="Difficulty" value={form.difficulty} onChange={(v) => set("difficulty", v)}
                  options={[{ value: "easy", label: "Easy" }, { value: "medium", label: "Medium" }, { value: "hard", label: "Hard" }]} />
              </div>
              <div>
                <p className="mb-1 text-sm">Length</p>
                <Segmented label="Length in minutes" value={form.duration_min} onChange={(v) => set("duration_min", v)}
                  options={[5, 10, 20, 30].map((m) => ({ value: m, label: `${m} min` }))} />
              </div>
            </div>
          </Card>

          <Card title="Your background">
            <fieldset>
              <legend className="text-sm">Resume</legend>
              <div className="mt-1 space-y-2">
                {resumes.map((r) => (
                  <label key={r.id} className="flex cursor-pointer items-start gap-3 rounded-lg p-2 hover:bg-wash">
                    <input type="radio" name="resume" className="mt-1 accent-[var(--accent)]" checked={resumeChoice === r.id} onChange={() => setResumeChoice(r.id)} />
                    <span className="text-sm">
                      <span className="font-medium">{r.parsed_profile.name ?? "Resume"}</span>
                      <span className="text-ink-2"> · uploaded {formatDate(r.created_at)}</span>
                      <span className="block text-xs text-ink-2">{r.parsed_profile.skills.slice(0, 6).join(", ")}</span>
                    </span>
                  </label>
                ))}
                <label className="flex cursor-pointer items-start gap-3 rounded-lg p-2 hover:bg-wash">
                  <input type="radio" name="resume" className="mt-1 accent-[var(--accent)]" checked={resumeChoice === "new"} onChange={() => setResumeChoice("new")} />
                  <span className="text-sm">
                    Upload a resume (PDF or DOCX)
                    {resumeChoice === "new" && <input type="file" accept=".pdf,.docx" className="mt-2 block text-sm text-ink-2" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg p-2 hover:bg-wash">
                  <input type="radio" name="resume" className="mt-1 accent-[var(--accent)]" checked={resumeChoice === "none"} onChange={() => setResumeChoice("none")} />
                  <span className="text-sm">Continue without a resume <span className="text-ink-2">(generic questions)</span></span>
                </label>
              </div>
            </fieldset>
            <label className="mt-4 block text-sm">
              Job description <span className="text-muted">(optional)</span>
              <textarea className={`${field} h-32`} value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the job post to get questions on the skills it asks for" />
            </label>
            {jdTooShort && <p className="mt-1 text-xs text-ink-2">Paste at least a few sentences (50+ characters), or leave it empty.</p>}
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="How you'll answer">
            <Segmented label="Answer mode" value={mode} onChange={setMode} options={[{ value: "voice", label: "Speak" }, { value: "text", label: "Type" }]} />
            {mode === "voice" ? (
              <div className="mt-4">
                <p className="text-sm text-ink-2">Check that your microphone picks you up. Say a sentence:</p>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-wash" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(mic.level * 100)}>
                  <div className="h-full rounded-full bg-accent transition-[width] duration-75" style={{ width: `${mic.level * 100}%` }} />
                </div>
                <Button type="button" variant="secondary" className="mt-3 w-full" onClick={() => setTestingMic(!testingMic)}>
                  {testingMic ? "Stop mic check" : "Test microphone"}
                </Button>
                {mic.error && <p className="mt-2 text-xs text-ink-2">{mic.error}</p>}
                <p className="mt-3 text-xs text-muted">Use headphones if you can, so Asha's voice isn't picked up. Audio is transcribed and never stored.</p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-ink-2">You'll type your answers. Asha's questions still appear as text.</p>
            )}
          </Card>
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button disabled={status !== null || jdTooShort || (resumeChoice === "new" && !file)} className="w-full py-3">
            {status ?? "Start interview"}
          </Button>
          {resumeChoice === "new" && !file && <p className="-mt-4 text-center text-xs text-ink-2">Choose a file, or pick another resume option.</p>}
        </div>
      </form>
    </main>
  );
}

const PHASE_LABEL: Record<Phase, string> = {
  connecting: "Connecting...",
  speaking: "Asha is speaking",
  listening: "Your turn",
  transcribing: "Transcribing...",
  thinking: "Asha is thinking...",
  ending: "Ending the interview...",
  ended: "Interview finished",
  error: "Disconnected",
};

function Room({ sessionId, voice }: { sessionId: string; voice: boolean }) {
  const { phase, lines, error, micReady, candidateSpeaking, progress, sendText, submitNow, end } = useVoiceInterview(sessionId, voice);
  const listening = phase === "listening";
  const mic = useMicLevel(voice && listening);
  const [text, setText] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [confirmEnd, setConfirmEnd] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Block body on purpose: newer Chrome returns a Promise from scrollIntoView, and an effect must not return one
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lines]);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const timeLeft = progress.timeLeftS == null ? null : progress.timeLeftS - (now - progress.receivedAt) / 1000;
  const { questionNumber: qn, totalQuestions: total } = progress;
  const label = listening ? (voice ? (candidateSpeaking ? "Listening..." : "Your turn - answer out loud") : "Your turn - type your answer") : PHASE_LABEL[phase];

  return (
    <main className="mx-auto flex h-[calc(100dvh-57px)] max-w-3xl flex-col gap-3 px-4 py-4">
      <div className="flex items-center gap-4 rounded-2xl bg-surface px-4 py-3 ring-1 ring-ring">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{qn && total ? `Question ${qn} of ${total}` : "Getting ready..."}</p>
          {total && (
            <div className="mt-1.5 flex gap-1" aria-hidden>
              {Array.from({ length: total }, (_, i) => (
                <span key={i} className={`h-1.5 flex-1 rounded-full ${qn && i < qn ? "bg-accent" : "bg-wash"}`} />
              ))}
            </div>
          )}
        </div>
        {timeLeft != null && phase !== "ended" && (
          <p className="shrink-0 text-right">
            <span className="block font-mono text-lg tabular-nums">{formatClock(timeLeft)}</span>
            <span className="text-xs text-muted">left</span>
          </p>
        )}
      </div>

      <div className="flex items-center gap-4 rounded-2xl bg-surface p-4 ring-1 ring-ring">
        <div className="relative grid h-14 w-14 shrink-0 place-items-center">
          {phase === "speaking" && (
            <>
              <span className="speak-ring absolute inset-0 rounded-full bg-accent" />
              <span className="speak-ring delay absolute inset-0 rounded-full bg-accent" />
            </>
          )}
          <span className="relative grid h-14 w-14 place-items-center rounded-full bg-button text-xl font-semibold text-on-accent">A</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">Asha</p>
          <p className="text-sm text-ink-2" aria-live="polite">{label}</p>
        </div>
        {voice && listening && (
          <div className="flex h-8 items-end gap-0.5" aria-hidden>
            {[0.6, 1, 0.8, 1, 0.6].map((w, i) => (
              <span key={i} className="w-1.5 rounded-full bg-good transition-[height] duration-75" style={{ height: `${Math.max(15, Math.min(100, mic.level * w * 130))}%` }} />
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-2xl bg-surface p-4 ring-1 ring-ring" aria-label="Conversation">
        {lines.length === 0 && <p className="text-sm text-muted">Asha will start in a moment...</p>}
        {lines.map((l, i) => (
          <div key={i} className={`flex ${l.speaker === "candidate" ? "justify-end" : ""}`}>
            <p className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${l.speaker === "candidate" ? "bg-button text-on-accent" : "bg-wash text-ink"}`}>{l.text}</p>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      {(error || mic.error) && phase !== "ended" && <ErrorNote>{error ?? mic.error}</ErrorNote>}

      {confirmEnd && phase !== "ended" && (
        <div role="alertdialog" aria-labelledby="end-title" className="rounded-2xl bg-surface p-4 ring-2 ring-critical">
          <p id="end-title" className="font-medium">End the interview now?</p>
          <p className="mt-1 text-sm text-ink-2">You'll get a report for the questions you've answered so far. This can't be undone.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button className="bg-critical hover:bg-critical" onClick={() => { setConfirmEnd(false); end(); }} autoFocus>
              Yes, end interview
            </Button>
            <Button variant="secondary" onClick={() => setConfirmEnd(false)}>Keep going</Button>
          </div>
        </div>
      )}

      {phase === "ended" ? (
        <LinkButton href={`#/report/${sessionId}`} className="py-3">See your feedback report</LinkButton>
      ) : phase === "error" ? (
        <LinkButton href="#/" variant="secondary" className="py-3">Back to your interviews</LinkButton>
      ) : (
        <div className="space-y-2">
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); sendText(text); setText(""); }}>
            <label className="sr-only" htmlFor="answer">Your answer</label>
            <input
              id="answer"
              className="min-w-0 flex-1 rounded-lg bg-surface px-3 py-2 text-sm ring-1 ring-ring focus:outline-none focus:ring-2 focus:ring-accent disabled:bg-wash"
              placeholder={voice && micReady ? "Or type your answer here" : "Type your answer"}
              value={text}
              disabled={!listening}
              onChange={(e) => setText(e.target.value)}
            />
            <Button disabled={!listening || !text.trim()}>Send</Button>
          </form>
          <div className="flex items-center justify-between">
            {voice ? (
              <Button variant="ghost" className="px-2" onClick={submitNow} disabled={!micReady || !listening}>I'm done answering</Button>
            ) : <span />}
            <Button variant="danger" onClick={() => setConfirmEnd(true)} disabled={confirmEnd || phase === "ending"}>
              End interview
            </Button>
          </div>
        </div>
      )}
    </main>
  );
}
