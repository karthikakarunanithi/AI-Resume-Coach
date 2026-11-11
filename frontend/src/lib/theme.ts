import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "coach_theme";
const EVENT = "coach-theme-change";

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice = read()) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(read);
  const set = (c: ThemeChoice) => {
    try {
      if (c === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, c);
    } catch {
      // storage unavailable: the choice lasts for this page view
    }
    applyTheme(c);
    setChoice(c);
    window.dispatchEvent(new Event(EVENT));
  };
  return [choice, set];
}

/** Resolved CSS color tokens for SVG charts; re-reads when the theme or OS scheme changes. */
export function useTokens<K extends string>(names: readonly K[]): Record<K, string> {
  const resolve = () => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(names.map((n) => [n, style.getPropertyValue(`--${n}`).trim()])) as Record<K, string>;
  };
  const [tokens, setTokens] = useState(resolve);
  useEffect(() => {
    const update = () => setTokens(resolve());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    window.addEventListener(EVENT, update);
    return () => {
      mq.removeEventListener("change", update);
      window.removeEventListener(EVENT, update);
    };
    // names is a constant tuple at every call site, so resolving once per theme change is enough
  }, []);
  return tokens;
}
