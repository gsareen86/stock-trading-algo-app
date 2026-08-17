/**
 * Login and logout, from the browser's point of view.
 *
 * The password crosses this route once and is never stored. Both tokens come back as httpOnly
 * cookies on this origin, so the login form has no token to mishandle — it posts credentials
 * and gets a redirect.
 */

import { NextRequest, NextResponse } from "next/server";

import {
  BACKEND_URL,
  clearSession,
  readRefreshToken,
  readSetCookie,
  storeSession,
} from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const { action, username, password } = await request.json();

  if (action === "logout") {
    const refresh = await readRefreshToken();
    if (refresh) {
      // Tell the backend to revoke, not just forget: a logout that invalidates nothing is
      // theatre, and the refresh token would otherwise stay valid for a fortnight.
      await fetch(`${BACKEND_URL}/auth/logout`, {
        method: "POST",
        headers: { Cookie: `refresh_token=${refresh}` },
        cache: "no-store",
      }).catch(() => undefined);
    }
    await clearSession();
    return NextResponse.json({ ok: true });
  }

  const response = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    cache: "no-store",
  });

  if (!response.ok) {
    // Echo the backend's single message: distinguishing "no such user" from "wrong password"
    // here would undo the care taken not to distinguish them there.
    return NextResponse.json({ detail: "Invalid username or password" }, { status: 401 });
  }

  const pair = await response.json();
  await storeSession(pair, readSetCookie(response.headers, "refresh_token"));
  return NextResponse.json({ ok: true, username: pair.username });
}
