import { resolveApiPath } from './book';

export const NETWORK_MESSAGE = "Steward couldn't reach your home server. Check that this device is on your home network or Tailscale.";

export class ApiError extends Error {
  status: number;
  /** The parsed JSON error body, when there was one: spec 8's 503 carries `last_saved`, a 409 carries `setup`. */
  body: unknown;
  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** True for the rejection of a request whose AbortSignal fired: a superseded request, never an error to show. */
export function isAbort(e: unknown): boolean {
  return typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError';
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}
/** A request made without api() (the chat stream) that got a 401 sends the person to sign in the same way. */
export function unauthorized() {
  onUnauthorized?.();
}

/** For requests that don't go through api() (an XHR upload): send the session-expired signal. */
export function notifyUnauthorized() {
  onUnauthorized?.();
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const headers: Record<string, string> = { Accept: 'application/json', ...(init.headers as Record<string, string> | undefined) };
  const typed = Object.keys(headers).some((k) => k.toLowerCase() === 'content-type');
  if (init.body !== undefined && !isForm && !typed) headers['Content-Type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(resolveApiPath(path), { credentials: 'same-origin', ...init, headers });
  } catch (e) {
    if (init.signal?.aborted || isAbort(e)) throw e;
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  if (res.status === 401 && !path.startsWith('/api/auth/')) onUnauthorized?.();
  if (!res.ok) {
    let message = `Something went wrong (${res.status}).`;
    let body: unknown = null;
    try {
      body = await res.json();
      const error = (body as { error?: unknown } | null)?.error;
      if (typeof error === 'string') message = error;
    } catch { /* body was not JSON; keep the generic message */ }
    throw new ApiError(res.status, message, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
export const patch = (body: unknown): RequestInit => ({ method: 'PATCH', body: JSON.stringify(body) });
export const put = (body: unknown): RequestInit => ({ method: 'PUT', body: JSON.stringify(body) });
export const del = (): RequestInit => ({ method: 'DELETE' });
