import { useState, type FormEvent } from "react";
import { ApiError, login, register } from "../api";
import { Button, ErrorNote } from "../components/ui";

const ERRORS: Record<string, string> = {
  LOGIN_BAD_CREDENTIALS: "Wrong email or password.",
  REGISTER_USER_ALREADY_EXISTS: "That email is already registered. Log in instead.",
};

export default function Login({ onLogin, startWithSignup = false }: { onLogin: () => void; startWithSignup?: boolean }) {
  const [mode, setMode] = useState<"login" | "register">(startWithSignup ? "register" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await register(email, password, name);
      await login(email, password);
      onLogin();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not reach the server.";
      setError(ERRORS[msg] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  const input = "mt-1 w-full rounded-lg bg-surface px-3 py-2 text-ink ring-1 ring-ring focus:outline-none focus:ring-2 focus:ring-accent";
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <a href="#/" className="mb-6 font-semibold">AI Interview Coach</a>
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl bg-surface p-6 ring-1 ring-ring">
        <h1 className="text-xl font-semibold">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
        {mode === "register" && (
          <label className="block text-sm">
            Name <span className="text-muted">(optional)</span>
            <input className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
        )}
        <label className="block text-sm">
          Email
          <input className={input} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label className="block text-sm">
          Password
          <input className={input} type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button disabled={busy} className="w-full">{busy ? "Please wait..." : mode === "login" ? "Log in" : "Sign up"}</Button>
        <p className="text-center text-sm text-ink-2">
          {mode === "login" ? "New here? " : "Already have an account? "}
          <button type="button" className="font-medium text-accent-strong hover:underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
            {mode === "login" ? "Create an account" : "Log in"}
          </button>
        </p>
      </form>
      <a href="#/demo" className="mt-4 text-sm text-ink-2 hover:underline">See a sample report first</a>
    </div>
  );
}
