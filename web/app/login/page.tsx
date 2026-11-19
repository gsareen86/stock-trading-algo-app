"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "login", username, password }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(body.detail ?? "Invalid username or password");
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[75vh] max-w-md flex-col justify-center px-6">
      <div className="hero-surface p-7">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-accent">
          Swing &amp; Long-Term
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight text-text-primary">Sign in</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Daily-driver Indian equity research &amp; paper-trading workstation.
        </p>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="username" className="block text-xs font-medium text-text-secondary">
              Username
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 w-full rounded-token border border-border-subtle bg-surface-raised px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-xs font-medium text-text-secondary">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-token border border-border-subtle bg-surface-raised px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>

          {error ? (
            <p role="alert" className="rounded-token bg-stance-avoid-soft px-3 py-2 text-xs font-medium text-stance-avoid">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-token bg-accent px-4 py-2.5 text-sm font-semibold text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-5 border-t border-border-subtle pt-4 text-xs text-text-muted">
          Session tokens stay in <code className="font-mono">httpOnly</code> cookies. Need an account? Run{" "}
          <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono">
            python -m app.auth.cli create-user &lt;name&gt;
          </code>
          .
        </p>
      </div>
    </div>
  );
}
