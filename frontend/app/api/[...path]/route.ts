/**
 * The API proxy.
 *
 * The browser talks to `/api/*` on its own origin and this handler forwards to
 * the backend, so the httpOnly session cookie stays first-party and there is no
 * CORS-credentials arrangement to get wrong.
 *
 * It is a route handler rather than a `next.config.ts` rewrite for one concrete
 * reason: Next resolves rewrite destinations at **build** time and bakes them
 * into `routes-manifest.json`. A standalone image built without
 * `API_INTERNAL_BASE` therefore proxies to `http://localhost:8000` forever, and
 * inside a container that is the frontend itself -- every request 500s with
 * `ECONNREFUSED`. That is exactly what happened. Read at request time, the
 * backend address is a deployment concern again.
 *
 * The upstream body is returned as a stream rather than buffered, because
 * `/api/v1/realtime/*` is Server-Sent Events and buffering would hold every
 * event until the connection closed.
 */

import type { NextRequest } from "next/server";

export const runtime = "nodejs";
// Never cached, never statically evaluated: every one of these is a live call.
export const dynamic = "force-dynamic";

const BACKEND = process.env.API_INTERNAL_BASE ?? "http://localhost:8000";

/** Hop-by-hop headers, plus the ones the fetch layer must set itself. */
const STRIP_REQUEST = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

const STRIP_RESPONSE = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "content-encoding",
  "content-length",
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const search = request.nextUrl.search;
  const target = `${BACKEND}/api/${path.map(encodeURIComponent).join("/")}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  // The backend reads the original client address for per-IP rate limiting.
  const forwarded = request.headers.get("x-forwarded-for");
  headers.set("x-forwarded-for", forwarded ?? "127.0.0.1");

  const hasBody = !["GET", "HEAD"].includes(request.method);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      // The body is streamed through, so a 20 MB evidence upload is not first
      // buffered in this process. `duplex` is required for a stream body.
      body: hasBody ? request.body : undefined,
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
    } as RequestInit & { duplex?: "half" });
  } catch (error) {
    // A typed envelope, so the client's `ApiError` handling still applies and a
    // dead backend does not surface as an unparseable 500.
    return Response.json(
      {
        error: {
          code: "BACKEND_UNREACHABLE",
          message: `The API could not be reached at ${BACKEND}.`,
          details: { reason: String(error) },
          request_id: request.headers.get("x-request-id") ?? "",
        },
      },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE.has(key.toLowerCase())) responseHeaders.append(key, value);
  });
  // `Headers.forEach` folds duplicate set-cookie values in some runtimes, so the
  // access and refresh cookies are re-applied from the raw list.
  const cookies = upstream.headers.getSetCookie?.() ?? [];
  if (cookies.length > 0) {
    responseHeaders.delete("set-cookie");
    for (const cookie of cookies) responseHeaders.append("set-cookie", cookie);
  }
  responseHeaders.set("cache-control", "no-store");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function POST(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function PUT(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function PATCH(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function DELETE(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function HEAD(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
export async function OPTIONS(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}
