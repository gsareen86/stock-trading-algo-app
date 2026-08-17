/**
 * Server-side session handling.
 *
 * Both tokens live in httpOnly cookies on the Next.js origin and are attached by the proxy
 * route. Page script never sees either one, which is the point: a token in `localStorage` is
 * readable by any injected script, and this app renders text fetched from the internet.
 *
 * This is a backend-for-frontend, not a token store — nothing here decides anything about
 * authorisation. The backend rejects a bad token regardless of what this file believes.
 */

import { cookies } from "next/headers";

export const ACCESS_COOKIE = "sw_access";
export const REFRESH_COOKIE = "sw_refresh";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

type TokenPair = {
  access_token: string;
  expires_in: number;
  username: string;
};

const cookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export async function storeSession(pair: TokenPair, refreshToken: string | null) {
  const jar = await cookies();
  jar.set(ACCESS_COOKIE, pair.access_token, {
    ...cookieOptions,
    // Slightly shorter than the token's own life so the cookie never outlives its contents.
    maxAge: Math.max(30, pair.expires_in - 30),
  });
  if (refreshToken) {
    jar.set(REFRESH_COOKIE, refreshToken, { ...cookieOptions, maxAge: 14 * 24 * 3600 });
  }
}

export async function clearSession() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}

export async function readAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_COOKIE)?.value ?? null;
}

export async function readRefreshToken(): Promise<string | null> {
  return (await cookies()).get(REFRESH_COOKIE)?.value ?? null;
}

/**
 * Exchange the refresh token for a new pair.
 *
 * Returns null rather than throwing when there is no usable session — an expired login is an
 * ordinary state that ends in a redirect, not an error worth a stack trace.
 */
export async function refreshSession(): Promise<TokenPair | null> {
  const refresh = await readRefreshToken();
  if (!refresh) return null;

  const response = await fetch(`${BACKEND_URL}/auth/refresh`, {
    method: "POST",
    headers: { Cookie: `refresh_token=${refresh}` },
    cache: "no-store",
  });
  if (!response.ok) return null;

  const pair = (await response.json()) as TokenPair;
  // The backend rotates on every refresh, so the new token has to be captured here or the
  // next request presents one that has already been revoked.
  const rotated = readSetCookie(response.headers, "refresh_token");
  await storeSession(pair, rotated);
  return pair;
}

/** Pull one cookie value out of a `set-cookie` response header. */
export function readSetCookie(headers: Headers, name: string): string | null {
  const raw = headers.getSetCookie?.() ?? [];
  for (const entry of raw) {
    const [pair] = entry.split(";");
    const [key, ...rest] = pair.split("=");
    if (key.trim() === name) return rest.join("=");
  }
  return null;
}
