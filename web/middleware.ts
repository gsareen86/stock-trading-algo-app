/**
 * Send signed-out visitors to the login page.
 *
 * A convenience, not a control: the backend rejects an unauthenticated request regardless of
 * what this decides. Middleware runs before a page renders, so it saves a round trip and an
 * empty screen — it does not protect anything, and nothing here should ever be the only thing
 * standing between a request and data.
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login", "/api/auth"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_ROUTES.some((route) => pathname.startsWith(route))) {
    return NextResponse.next();
  }
  if (request.cookies.get("sw_refresh")) {
    return NextResponse.next();
  }

  const login = new URL("/login", request.url);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
