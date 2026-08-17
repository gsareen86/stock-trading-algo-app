"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * The login form.
 *
 * It holds no token. Credentials post to `/api/auth`, which stores httpOnly cookies and
 * returns nothing sensitive — so there is no token here for a script to read or for this
 * component to mislay.
 */
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
    <div className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center px-6">
      <h1 className="text-lg font-semibold text-text-primary">Sign in</h1>
      <p className="mt-1 text-sm text-text-muted">
        Paper-trading research platform. Indian equities.
      </p>

      <form onSubmit={submit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="username" className="block text-xs text-text-muted">
            Username
          </label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-sm text-text-primary"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-xs text-text-muted">
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
            className="mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-sm text-text-primary"
          />
        </div>

        {error ? (
          <p role="alert" className="text-sm text-stance-avoid">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-token bg-text-primary px-3 py-2 text-sm font-medium text-surface-sunken disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-6 text-xs text-text-muted">
        No account yet? Create one from the backend:{" "}
        <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono">
          python -m app.auth.cli create-user &lt;name&gt;
        </code>
      </p>
    </div>
  );
}
