import { useEffect, useMemo, useState } from "react";
import { ApiError, getProgress, listSessions, type Progress } from "../api";
import { BarList, ScoreTrend } from "../components/charts";
import { Card, ErrorNote, LinkButton, Segmented, SignalBadge, Spinner, StatTile } from "../components/ui";
import { formatDate, interviewTypeLabel, titleCase } from "../lib/format";
import type { SessionSummary } from "../types";

const STATUS: Record<SessionSummary["status"], string> = {
  planning: "Planning",
  in_progress: "In progress",
  scoring: "Scoring...",
  done: "Done",
  failed: "Failed",
};
type TypeFilter = "all" | SessionSummary["interview_type"];

export default function Dashboard({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [type, setType] = useState<TypeFilter>("all");

  useEffect(() => {
    Promise.all([getProgress(), listSessions()])
      .then(([p, s]) => {
        setProgress(p);
        setSessions(s);
      })
      .catch((e) => (e instanceof ApiError && e.status === 401 ? onUnauthorized() : setError(e.message ?? String(e))));
  }, [onUnauthorized]);

  const types = useMemo(() => [...new Set((sessions ?? []).map((s) => s.interview_type))], [sessions]);
  // The filter scopes everything below it, so the chart and table always agree
  const points = (progress?.points ?? []).filter((p) => type === "all" || p.interview_type === type);
  const rows = (sessions ?? []).filter((s) => type === "all" || s.interview_type === type);

  if (error) return <main className="mx-auto max-w-5xl px-4 py-8"><ErrorNote>{error}</ErrorNote></main>;
  if (!progress || !sessions) return <main className="mx-auto max-w-5xl px-4 py-8"><Spinner label="Loading your progress..." /></main>;

  if (sessions.length === 0) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16 text-center">
        <h1 className="text-2xl font-semibold">Your first mock interview is a few clicks away</h1>
        <p className="mx-auto mt-2 max-w-md text-ink-2">Add your resume, pick a role and talk to Asha. Your scores and progress will show up here.</p>
        <div className="mt-6 flex justify-center gap-3">
          <LinkButton href="#/interview">Start an interview</LinkButton>
          <LinkButton href="#/demo" variant="secondary">See a sample report</LinkButton>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Your progress</h1>
        {types.length > 1 && (
          <Segmented label="Interview type" value={type} onChange={setType}
            options={[{ value: "all", label: "All" }, ...types.map((t) => ({ value: t as TypeFilter, label: interviewTypeLabel(t) }))]} />
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Interviews scored" value={progress.interviews} />
        <StatTile label="Latest score" value={progress.last_score ?? "-"} delta={progress.change_vs_previous} deltaLabel="vs previous" />
        <StatTile label="Average score" value={progress.avg_score ?? "-"} />
        <StatTile label="Best score" value={progress.best_score ?? "-"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Overall score over time" className="lg:col-span-3">
          {points.length >= 2 ? (
            <ScoreTrend points={points} />
          ) : (
            <p className="py-16 text-center text-sm text-ink-2">Finish one more interview to see your trend.</p>
          )}
        </Card>
        <Card title="Topics to work on" className="lg:col-span-2">
          {progress.weakest_topics.length ? (
            <BarList
              caption="Average score per topic, weakest first"
              max={100}
              items={progress.weakest_topics.map((t) => ({ label: titleCase(t.topic), value: t.avg_score, detail: `${t.questions} question${t.questions === 1 ? "" : "s"}` }))}
            />
          ) : (
            <p className="py-16 text-center text-sm text-ink-2">Topic scores appear after your first scored interview.</p>
          )}
        </Card>
      </div>

      <Card title="History">
        <div className="-mx-5 sm:-mx-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="px-5 py-2 font-medium sm:px-6">Date</th>
                <th className="py-2 font-medium">Role</th>
                <th className="hidden py-2 font-medium sm:table-cell">Type</th>
                <th className="py-2 text-right font-medium">Score</th>
                <th className="px-5 py-2 font-medium sm:px-6">Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-line last:border-0 hover:bg-wash">
                  <td className="whitespace-nowrap px-5 py-3 tabular-nums text-ink-2 sm:px-6">{formatDate(s.created_at)}</td>
                  <td className="py-3 pr-2">
                    <a href={`#/report/${s.id}`} className="font-medium hover:underline">{s.role}</a>
                    <span className="block text-xs text-ink-2 sm:hidden">{interviewTypeLabel(s.interview_type)} · {s.difficulty}</span>
                  </td>
                  <td className="hidden py-3 text-ink-2 sm:table-cell">{interviewTypeLabel(s.interview_type)} · {s.difficulty}</td>
                  <td className="py-3 text-right font-semibold tabular-nums">{s.overall_score ?? ""}</td>
                  <td className="whitespace-nowrap px-5 py-3 sm:px-6">
                    {s.hiring_signal ? <SignalBadge signal={s.hiring_signal} /> : <span className="text-ink-2">{STATUS[s.status]}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </main>
  );
}
