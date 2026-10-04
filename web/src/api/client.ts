/**
 * The one place the SPA talks to the API.
 *
 * Every call carries the access token the auth provider holds. Errors arrive as
 * `{ error: { code, message } }` and are turned into an `ApiError` so features
 * can show the message near the thing that failed rather than a generic banner.
 */

import { loadConfig } from "../config";

/**
 * Resolved on first request, never at import time.
 *
 * Reading configuration while this module is being imported makes a bad value
 * throw during the import graph's evaluation — before any error handling in
 * main.tsx has had a chance to run — and the page renders nothing at all.
 */
let base: string | null = null;

function apiBase(): string {
  base ??= loadConfig().apiBaseUrl;
  return base;
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** How long to wait, as a person says it: whole units, rounded up. */
export function getWaitLabel(seconds: number): string {
  if (seconds <= 60) return "a minute";
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} minutes`;
  const hours = Math.ceil(seconds / 3600);
  return hours === 1 ? "an hour" : `${hours} hours`;
}

/**
 * What to say when a request was refused with no `{error}` envelope: the
 * edge proxy answers 413 and 429 itself (ADR 0053), and 502 while the api
 * restarts. The app's own refusals carry their message, and keep it.
 */
export function getRefusalMessage(
  status: number,
  retryAfter: string | null,
): string {
  if (status === 429) {
    const seconds = Number(retryAfter);
    return seconds > 0
      ? `Too many requests. Try again in ${getWaitLabel(seconds)}.`
      : "Too many requests. Try again shortly.";
  }
  if (status === 413) return "That file is too large to upload.";
  if (status === 502 || status === 503 || status === 504) {
    return "The server is not answering. Try again in a moment.";
  }
  return `Request failed (${status})`;
}

/** The error envelope, if the body is one: an edge's page is not JSON. */
function getEnvelope(
  text: string,
): { code?: string; message?: string } | undefined {
  try {
    const parsed = JSON.parse(text) as {
      error?: { code?: string; message?: string };
    } | null;
    return parsed?.error;
  } catch {
    return undefined;
  }
}

function getApiError(response: Response, text: string): ApiError {
  const envelope = getEnvelope(text);
  return new ApiError(
    envelope?.code ?? "unknown",
    envelope?.message ??
      getRefusalMessage(response.status, response.headers.get("retry-after")),
    response.status,
  );
}

type TokenSource = () => Promise<string | null>;

let getToken: TokenSource = async () => null;

/** Registered by the auth provider; not a React hook. */
export function setTokenSource(source: TokenSource): void {
  getToken = source;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(`${apiBase()}/api/v1${path}`, {
    ...init,
    headers,
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!response.ok) throw getApiError(response, text);
  return (text ? JSON.parse(text) : null) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  /**
   * The items of a list endpoint, typed by its generated page (`RolePage`, …).
   * Without a `page_size` in `path` the API sends the whole list (ADR 0014).
   */
  items: <P extends { items: unknown[] }>(path: string) =>
    request<P>(path).then((page) => page.items as P["items"]),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : null,
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** A file as multipart form data, with any plain fields beside it; a
   * null field is left out. */
  upload: <T>(
    path: string,
    file: File,
    fields: Record<string, string | null> = {},
  ) => {
    const form = new FormData();
    for (const [name, value] of Object.entries(fields)) {
      if (value !== null) form.append(name, value);
    }
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};

export interface ServerEvent {
  event: string;
  data: string;
}

/** Split an SSE buffer into complete events and what is left over. Pure. */
export function parseEvents(buffer: string): {
  events: ServerEvent[];
  rest: string;
} {
  const normalised = buffer.replace(/\r\n/g, "\n");
  const blocks = normalised.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ServerEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:"))
        data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length > 0) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

/**
 * POST and read Server-Sent Events as they arrive.
 *
 * `EventSource` can neither POST a body nor send the bearer token, so the
 * résumé chat reads the stream itself. A refusal before streaming starts
 * throws an `ApiError`, as any other call would.
 */
export async function streamEvents(
  path: string,
  body: unknown,
  onEvent: (event: ServerEvent) => void,
): Promise<void> {
  const token = await getToken();
  const headers = new Headers({
    "content-type": "application/json",
    accept: "text/event-stream",
  });
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase()}/api/v1${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw getApiError(response, await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseEvents(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const { events } = parseEvents(`${buffer}\n\n`);
  events.forEach(onEvent);
}
