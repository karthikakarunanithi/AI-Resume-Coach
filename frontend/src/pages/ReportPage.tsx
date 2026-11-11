import { useEffect, useState } from "react";
import { ApiError, getReport, getSampleReport } from "../api";
import Report from "../components/Report";
import { ErrorNote, LinkButton, Spinner } from "../components/ui";
import type { FinalReport } from "../types";

const POLL_MS = 3000;

type Props = { sample: true } | { sample?: false; sessionId: string; onUnauthorized: () => void };

export default function ReportPage(props: Props) {
  const [report, setReport] = useState<FinalReport | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = props.sample ? null : props.sessionId;
  const onUnauthorized = props.sample ? null : props.onUnauthorized;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function load() {
      try {
        const r = sessionId ? await getReport(sessionId) : await getSampleReport();
        if (cancelled) return;
        if (r) {
          setReport(r);
          setPending(false);
        } else {
          setPending(true); // still running or being scored: poll until ready
          timer = window.setTimeout(load, POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401 && onUnauthorized) onUnauthorized();
        else setError(e instanceof ApiError ? e.message : "Could not load the report.");
      }
    }
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [sessionId, onUnauthorized]);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {props.sample && (
        <div className="no-print mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-accent-wash px-4 py-3">
          <p className="text-sm text-ink">This is a sample report with made-up answers.</p>
          <LinkButton href="#/login?signup">Try it with your resume</LinkButton>
        </div>
      )}
      {!props.sample && <a href="#/" className="no-print mb-4 inline-block text-sm text-accent-strong hover:underline">← All interviews</a>}
      {error && <ErrorNote>{error}</ErrorNote>}
      {pending && (
        <div className="rounded-2xl bg-surface p-8 ring-1 ring-ring">
          <Spinner label="Scoring your answers. This page updates by itself, usually within a minute." />
        </div>
      )}
      {!report && !pending && !error && <Spinner label="Loading..." />}
      {report && <Report report={report} sample={props.sample} />}
    </main>
  );
}
