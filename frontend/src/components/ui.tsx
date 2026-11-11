import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`print-break rounded-2xl bg-surface p-5 ring-1 ring-ring sm:p-6 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="font-semibold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-button text-on-accent hover:bg-button-hover",
  secondary: "bg-surface text-ink ring-1 ring-ring hover:bg-wash",
  ghost: "text-accent-strong hover:bg-wash",
  danger: "text-critical ring-1 ring-ring hover:bg-wash",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${className}`}
    />
  );
}

export function LinkButton({ href, variant = "primary", children, className = "" }: { href: string; variant?: Variant; children: ReactNode; className?: string }) {
  return (
    <a href={href} className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${VARIANT[variant]} ${className}`}>
      {children}
    </a>
  );
}

/** Stat tile: label, value in proportional figures, optional delta vs a named period. */
export function StatTile({ label, value, delta, deltaLabel, upIsGood = true }: { label: string; value: ReactNode; delta?: number | null; deltaLabel?: string; upIsGood?: boolean }) {
  const good = delta != null && delta !== 0 && delta > 0 === upIsGood;
  return (
    <div className="rounded-2xl bg-surface p-4 ring-1 ring-ring">
      <p className="text-sm text-ink-2">{label}</p>
      <p className="mt-1 text-3xl font-semibold">{value}</p>
      {delta != null && (
        <p className="mt-1 flex items-center gap-1 text-xs text-ink-2">
          <span aria-hidden className={delta === 0 ? "text-muted" : good ? "text-good" : "text-critical"}>
            {delta > 0 ? "▲" : delta < 0 ? "▼" : "●"}
          </span>
          {delta > 0 ? `+${delta}` : delta} {deltaLabel}
        </p>
      )}
    </div>
  );
}

const SIGNAL: Record<string, { color: string; icon: string }> = {
  Strong: { color: "bg-good", icon: "✓" },
  "Lean yes": { color: "bg-good", icon: "↗" },
  "Lean no": { color: "bg-warning", icon: "↘" },
  "Not yet": { color: "bg-critical", icon: "✕" },
};

/** Status never relies on color alone: icon + label, text in ink. */
export function SignalBadge({ signal }: { signal: string }) {
  const s = SIGNAL[signal] ?? { color: "bg-muted", icon: "•" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-wash px-2.5 py-0.5 text-xs font-medium text-ink">
      <span aria-hidden className={`grid h-3.5 w-3.5 place-items-center rounded-full text-[9px] leading-none text-white ${s.color}`}>{s.icon}</span>
      {signal}
    </span>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-ink-2" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
      {label}
    </p>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-lg bg-wash px-3 py-2 text-sm text-ink" role="alert">
      <span aria-hidden className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-critical text-[10px] text-white">!</span>
      {children}
    </p>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-lg bg-wash p-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm transition-colors ${value === o.value ? "bg-surface font-medium text-ink shadow-sm ring-1 ring-ring" : "text-ink-2 hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
