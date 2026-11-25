import type { BrowserSession } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status);
  }
  return body as T;
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  csrf?: string,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrf && method !== "GET") headers["X-Orin-CSRF"] = csrf;
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  });
  return readJson<T>(response);
}

export function getBrowserSession(): Promise<BrowserSession> {
  return request<BrowserSession>("/auth/session");
}

export function getBootstrap(): Promise<{ pairing_available: boolean }> {
  return request("/auth/bootstrap");
}

export function pairBrowser(code: string): Promise<BrowserSession> {
  return request<BrowserSession>("/auth/pair", "POST", { code });
}

export function logoutBrowser(csrf: string): Promise<{ logged_out: boolean }> {
  return request("/auth/logout", "POST", undefined, csrf);
}

export class OrinClient {
  constructor(private readonly csrf: string) {}

  get<T>(path: string): Promise<T> {
    return request<T>(path);
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, "POST", body, this.csrf);
  }
}
