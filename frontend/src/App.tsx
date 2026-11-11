import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { getToken, setToken } from "./api";
import { Spinner } from "./components/ui";
import { useTheme, type ThemeChoice } from "./lib/theme";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import ReportPage from "./pages/ReportPage";

// Loaded on demand: the voice room pulls in the VAD model runtime (ONNX), which the other pages don't need
const Interview = lazy(() => import("./pages/Interview"));

// Hash routes: #/ (landing or dashboard), #/login, #/interview, #/report/<id>, #/demo (sample report, no login)
type Route = { name: "home" } | { name: "login"; signup: boolean } | { name: "interview" } | { name: "report"; id: string } | { name: "demo" };

function parseHash(): Route {
  const [path, query = ""] = window.location.hash.replace(/^#/, "").split("?");
  const [, page, id] = path.split("/");
  if (page === "report" && id) return { name: "report", id };
  if (page === "demo") return { name: "demo" };
  if (page === "interview") return { name: "interview" };
  if (page === "login") return { name: "login", signup: query.includes("signup") };
  return { name: "home" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash);
  const [authed, setAuthed] = useState(() => Boolean(getToken()));

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Stable identity: pages list it as an effect dependency
  const logout = useCallback(() => {
    setToken(null);
    setAuthed(false);
  }, []);

  if (route.name === "demo") {
    return <Shell authed={authed} onLogout={logout}><ReportPage sample /></Shell>;
  }
  if (!authed) {
    if (route.name === "home") return <Landing />;
    // Logging in from #/login lands on the dashboard; from a deep link (e.g. a report) it stays there
    const onLogin = () => {
      setAuthed(true);
      if (route.name === "login") window.location.hash = "#/";
    };
    return <Login onLogin={onLogin} startWithSignup={route.name === "login" && route.signup} />;
  }

  return (
    <Shell authed onLogout={logout}>
      {route.name === "report" ? (
        <ReportPage sessionId={route.id} onUnauthorized={logout} />
      ) : route.name === "interview" ? (
        <Suspense fallback={<main className="mx-auto max-w-5xl px-4 py-8"><Spinner label="Loading..." /></main>}>
          <Interview onUnauthorized={logout} />
        </Suspense>
      ) : (
        <Dashboard onUnauthorized={logout} />
      )}
    </Shell>
  );
}

const NEXT_THEME: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Auto", light: "Light", dark: "Dark" };

function Shell({ authed, onLogout, children }: { authed: boolean; onLogout: () => void; children: ReactNode }) {
  const [theme, setTheme] = useTheme();
  return (
    <div className="min-h-screen">
      <header className="no-print sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <a href="#/" className="truncate font-semibold">
            <span className="hidden sm:inline">AI </span>Interview Coach
          </a>
          <nav className="flex shrink-0 items-center gap-1 whitespace-nowrap text-sm sm:gap-2">
            <button onClick={() => setTheme(NEXT_THEME[theme])} className="rounded-lg px-2 py-1.5 text-ink-2 hover:bg-wash" title="Switch color theme" aria-label={`Color theme: ${THEME_LABEL[theme]}`}>
              <span className="hidden sm:inline">Theme: </span>{THEME_LABEL[theme]}
            </button>
            {authed ? (
              <>
                <a href="#/interview" className="rounded-lg bg-button px-3 py-1.5 font-medium text-on-accent hover:bg-button-hover">
                  New<span className="hidden sm:inline"> interview</span>
                </a>
                <button onClick={onLogout} className="rounded-lg px-2 py-1.5 text-ink-2 hover:bg-wash">Log out</button>
              </>
            ) : (
              <a href="#/login" className="rounded-lg px-2 py-1.5 font-medium text-accent-strong hover:bg-wash">Log in</a>
            )}
          </nav>
        </div>
      </header>
      {children}
    </div>
  );
}
