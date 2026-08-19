/**
 * Session upkeep, before a page renders.
 *
 * Two jobs, and the second is load-bearing:
 *
 * 1. Send signed-out visitors to the login page. A convenience, not a control — the backend
 *    rejects an unauthenticated request regardless of what this decides, and nothing here
 *    should ever be the only thing between a request and data.
 *
 * 2. **Renew an expired access token.** Server components read the access cookie directly and
 *    cannot set cookies, so without this a short-lived token would simply expire and every
 *    surface would render as signed-out until the user logged in again. Middleware is the one
 *    place in the render path that can both read the refresh cookie and write a new access
 *    cookie.
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login", "/api/auth"];
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_ROUTES.some((route) => pathname.startsWith(route))) {
    return NextResponse.next();
  }

  const refresh = request.cookies.get("sw_refresh")?.value;
  if (!refresh) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (request.cookies.get("sw_access")) {
    return NextResponse.next();
  }

  // Access token has expired but the session has not. Renew once; a failure here means the
  // refresh token is spent or revoked, which is a login, not a retry.
  try {
    const response = await fetch(`${BACKEND_URL}/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `refresh_token=${refresh}` },
      cache: "no-store",
    });
    if (!response.ok) {
      const redirect = NextResponse.redirect(new URL("/login", request.url));
      redirect.cookies.delete("sw_refresh");
      return redirect;
    }

    const pair = await response.json();
    const next = NextResponse.next();
    const options = {
      httpOnly: true,
      sameSite: "lax" as const,
      secure: process.env.NODE_ENV === "production",
      path: "/",
    };
    next.cookies.set("sw_access", pair.access_token, {
      ...options,
      maxAge: Math.max(30, pair.expires_in - 30),
    });
    // The backend rotates on every refresh, so the replacement has to be captured here or the
    // next renewal presents a token that has already been revoked.
    const rotated = response.headers
      .getSetCookie?.()
      .map((entry) => entry.split(";")[0])
      .find((pairText) => pairText.startsWith("refresh_token="));
    if (rotated) {
      next.cookies.set("sw_refresh", rotated.slice("refresh_token=".length), {
        ...options,
        maxAge: 14 * 24 * 3600,
      });
    }
    return next;
  } catch {
    return NextResponse.redirect(new URL("/login", request.url));
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
