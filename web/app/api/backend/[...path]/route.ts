/**
 * The proxy every page reaches the backend through.
 *
 * It attaches the access token from an httpOnly cookie and, on a 401, refreshes **once**
 * before giving up. Once, because a refresh loop against a dead session is how a login page
 * becomes an infinite redirect — and because if a freshly minted token is also rejected, the
 * problem is not staleness.
 */

import { NextRequest, NextResponse } from "next/server";

import { BACKEND_URL, readAccessToken, refreshSession } from "@/lib/session";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, path: string[]) {
  const target = `${BACKEND_URL}/${path.join("/")}${request.nextUrl.search}`;
  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.text();

  const send = async (token: string | null) =>
    fetch(target, {
      method: request.method,
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      cache: "no-store",
    });

  let response = await send(await readAccessToken());

  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (!refreshed) {
      // No usable session. The client turns this into a redirect to /login.
      return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
    }
    response = await send(refreshed.access_token);
  }

  const contentType = response.headers.get("content-type") ?? "application/json";
  if (contentType.includes("text/event-stream") && response.body) {
    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  }

  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: { "Content-Type": contentType },
  });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

