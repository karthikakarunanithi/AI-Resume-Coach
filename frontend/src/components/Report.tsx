import { useState } from "react";
import { titleCase, interviewTypeLabel, formatDate, formatClock } from "../lib/format";
import type { FinalReport, QuestionReport, SpeechSummary } from "../types";
import { BarList } from "./charts";
import { Button, Card, LinkButton, SignalBadge } from "./ui";

export default function Report({ report: r, sample = false }: { report: FinalReport; sample?: boolean }) {
  const dims = Object.entries(r.dimension_scores);
  const unscored = r.questions_answered > 0 && r.questions_scored === 0;
  const [expandAll, setExpandAll] = useState(false);

  const printPdf = () => {
    setExpandAll(true); // show transcripts and sample answers in the PDF
    window.setTimeout(() => {
      window.print();
      setExpandAll(false);
    }, 50);
  };

  return (
    <div className="space-y-6">
      <section className="print-break rounded-2xl bg-surface p-6 ring-1 ring-ring">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <p className="text-sm text-ink-2">
              {interviewTypeLabel(r.interview_type)} interview · {r.difficulty} · {formatDate(r.generated_at, true)}
            </p>
            <h1 className="mt-1 text-2xl font-semibold">{r.role}</h1>
            <p className="mt-1 text-sm text-ink-2">Answered {r.questions_answered} of {r.questions_planned} planned questions</p>
          </div>
          <div className="text-right">
            {unscored ? (
              <p className="text-2xl font-semibold text-ink-2">Not scored</p>
            ) : (
              <>
                <p className="text-6xl font-semibold leading-none">
                  {r.overall_score}
                  <span className="text-xl font-normal text-muted">/100</span>
                </p>
                <div className="mt-3"><SignalBadge signal={r.hiring_signal} /></div>
              </>
            )}
          </div>
        </div>
        <p className="mt-5 leading-relaxed text-ink">{r.summary}</p>
        {!r.coach_generated && r.questions_answered > 0 && (
          <p className="mt-2 text-xs text-muted">Detailed coaching was unavailable for this session; scores are complete.</p>
        )}
        {!sample && (
          <div className="no-print mt-5 flex flex-wrap gap-2">
            <LinkButton href="#/interview">Practise again</LinkButton>
            <Button variant="secondary" onClick={printPdf}>Download PDF</Button>
          </div>
        )}
      </section>

      {dims.length > 0 && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card title="Rubric scores">
            <BarList
              caption="Average score per rubric dimension, out of 5"
              max={5}
              format={(v) => v.toFixed(1)}
              items={dims.map(([d, v]) => ({ label: titleCase(d), value: v, detail: "out of 5, averaged over your answers" }))}
            />
            <p className="mt-4 text-xs text-muted">1 = missing or wrong, 3 = acceptable, 5 = excellent. Scores need a quote from your answer as evidence.</p>
          </Card>
          <div className="space-y-6">
            <ListCard title="Strengths" items={r.strengths} marker="bg-good" />
            <ListCard title="Focus areas" items={r.improvements} marker="bg-warning" />
          </div>
        </div>
      )}

      {r.speech && <SpeechPanel speech={r.speech} />}

      {r.practice_plan.length > 0 && (
        <Card title="Your 7-day practice plan">
          <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {r.practice_plan.map((d) => (
              <li key={d.day} className="print-break rounded-xl bg-wash p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-accent-strong">Day {d.day}</p>
                <p className="font-medium">{d.focus}</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-ink-2">
                  {d.tasks.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {r.questions.length > 0 && (
        <section className="space-y-4">
          <h2 className="font-semibold">Question by question</h2>
          {r.questions.map((q, i) => <QuestionCard key={q.question_id} q={q} n={i + 1} expandAll={expandAll} seconds={r.speech?.answer_seconds[q.question_id]} />)}
        </section>
      )}
    </div>
  );
}

function ListCard({ title, items, marker }: { title: string; items: string[]; marker: string }) {
  if (items.length === 0) return null;
  return (
    <Card title={title}>
      <ul className="space-y-2.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2.5 text-sm text-ink">
            <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${marker}`} />
            {item}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SpeechPanel({ speech: s }: { speech: SpeechSummary }) {
  const fillers = Object.entries(s.filler_counts).slice(0, 4);
  const paceNote = s.pace === "good" ? "Comfortable pace" : s.pace ? `A bit ${s.pace}; aim for 120-160` : "";
  const stats: [string, string, string][] = [
    ["Pace", s.avg_wpm ? `${Math.round(s.avg_wpm)} wpm` : "-", paceNote],
    ["Filler words", `${s.fillers_per_100_words}`, `per 100 words${fillers.length ? ` · ${fillers.map(([w, n]) => `"${w}" ${n}`).join(", ")}` : ""}`],
    ["Long pauses", String(s.long_pauses), "silences over 2 seconds"],
    ["Hedging", String(s.hedges), `"maybe", "not sure", "I guess"`],
  ];
  return (
    <Card title="How you sounded">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map(([title, value, note]) => (
          <div key={title} className="rounded-xl bg-wash p-3">
            <p className="text-sm text-ink-2">{title}</p>
            <p className="text-2xl font-semibold">{value}</p>
            <p className="mt-0.5 text-xs text-ink-2">{note}</p>
          </div>
        ))}
      </div>
      {s.flags.length > 0 && (
        <ul className="mt-4 space-y-1.5 text-sm text-ink">
          {s.flags.map((f, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-warning" />
              {f}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function QuestionCard({ q, n, expandAll, seconds }: { q: QuestionReport; n: number; expandAll: boolean; seconds?: number }) {
  const [open, setOpen] = useState<"transcript" | "sample" | null>(null);
  const show = (k: "transcript" | "sample") => expandAll || open === k;
  const toggle = (k: "transcript" | "sample") => setOpen(open === k ? null : k);

  return (
    <article className="print-break rounded-2xl bg-surface p-5 ring-1 ring-ring sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">
            Question {n} · {titleCase(q.topic)}{seconds ? ` · answered in ${formatClock(seconds)}` : ""}
          </p>
          <h3 className="mt-1 font-medium">{q.text}</h3>
        </div>
        {q.score !== null ? (
          <p className="shrink-0 text-2xl font-semibold">{q.score}<span className="text-sm font-normal text-muted">/100</span></p>
        ) : (
          <span className="shrink-0 text-sm text-muted">Not scored</span>
        )}
      </div>

      {q.evaluated && (
        <dl className="mt-4 divide-y divide-line">
          {Object.entries(q.scores).map(([dim, score]) => (
            <div key={dim} className="grid gap-1 py-2 sm:grid-cols-[9rem_1fr] sm:gap-4">
              <dt className="flex items-center gap-2 text-sm">
                <span className="text-ink-2">{titleCase(dim)}</span>
                <span className="font-medium tabular-nums">{score}/5</span>
              </dt>
              <dd className="text-sm text-ink-2">
                {q.evidence[dim] ? <q className="italic">{q.evidence[dim]}</q> : <span className="text-muted">No supporting evidence in the answer</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {(q.missed_key_points.length > 0 || q.improvements.length > 0) && (
        <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
          {q.missed_key_points.length > 0 && (
            <div>
              <p className="font-medium">Missed key points</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-2">{q.missed_key_points.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          {q.improvements.length > 0 && (
            <div>
              <p className="font-medium">How to improve</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-2">{q.improvements.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      <div className="no-print mt-4 flex gap-1">
        <Button variant="ghost" className="px-2" onClick={() => toggle("transcript")} aria-expanded={show("transcript")}>
          {show("transcript") ? "Hide" : "Show"} transcript
        </Button>
        {q.sample_answer && (
          <Button variant="ghost" className="px-2" onClick={() => toggle("sample")} aria-expanded={show("sample")}>
            {show("sample") ? "Hide" : "Show"} a stronger answer
          </Button>
        )}
      </div>
      {show("transcript") && (
        <div className="mt-3 space-y-2 rounded-xl bg-wash p-3 text-sm">
          {q.transcript.map((t, i) => (
            <p key={i}>
              <span className="font-medium">{t.speaker === "interviewer" ? "Asha" : "You"}:</span> <span className="text-ink-2">{t.text}</span>
            </p>
          ))}
        </div>
      )}
      {show("sample") && q.sample_answer && (
        <div className="mt-3 rounded-xl bg-accent-wash p-3 text-sm leading-relaxed text-ink">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-accent-strong">A stronger answer</p>
          {q.sample_answer}
        </div>
      )}
    </article>
  );
}
