import { LinkButton } from "../components/ui";

const STEPS = [
  { n: 1, title: "Add your resume and the job", body: "Questions are planned from your own projects and the skills the job description asks for." },
  { n: 2, title: "Talk to Asha", body: "A voice interviewer asks one question at a time and follows up when an answer is vague or worth probing." },
  { n: 3, title: "Get a scored report", body: "Every score quotes what you actually said, with missed points, a stronger sample answer and a 7-day plan." },
];

const FEATURES = [
  ["Grounded in your resume", "Deep-dive questions on your real projects, not generic lists."],
  ["Technical, system design, behavioral, HR", "Pick the round and difficulty you want to practise."],
  ["Evidence-based scoring", "A fixed rubric; a score without a quote from your answer is capped."],
  ["How you sound", "Pace, filler words, long pauses and hedging from your spoken answers."],
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
        <span className="font-semibold">AI Interview Coach</span>
        <a href="#/login" className="text-sm font-medium text-accent-strong hover:underline">Log in</a>
      </header>

      <main className="mx-auto max-w-5xl px-4">
        <section className="py-12 sm:py-20">
          <p className="text-sm font-medium text-accent-strong">Mock interviews for AI, ML and GenAI roles</p>
          <h1 className="mt-3 max-w-2xl text-4xl font-semibold leading-tight sm:text-5xl">
            Practise out loud. Get feedback you can act on.
          </h1>
          <p className="mt-4 max-w-xl text-lg text-ink-2">
            A voice interviewer that asks about your own projects, follows up like a real panel, and scores every answer with evidence.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <LinkButton href="#/login?signup">Start practising, it's free</LinkButton>
            <LinkButton href="#/demo" variant="secondary">See a sample report</LinkButton>
          </div>
        </section>

        <section className="grid gap-4 pb-12 sm:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.n} className="rounded-2xl bg-surface p-5 ring-1 ring-ring">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-accent-wash text-sm font-semibold text-accent-strong">{s.n}</span>
              <h2 className="mt-3 font-semibold">{s.title}</h2>
              <p className="mt-1 text-sm text-ink-2">{s.body}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-x-8 gap-y-5 border-t border-line py-12 sm:grid-cols-2">
          {FEATURES.map(([title, body]) => (
            <div key={title} className="flex gap-3">
              <span aria-hidden className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent" />
              <div>
                <h3 className="font-medium">{title}</h3>
                <p className="text-sm text-ink-2">{body}</p>
              </div>
            </div>
          ))}
        </section>
      </main>

      <footer className="border-t border-line py-6 text-center text-xs text-muted">
        Audio is transcribed and never stored.
      </footer>
    </div>
  );
}
