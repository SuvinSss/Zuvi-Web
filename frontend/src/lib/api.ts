export interface ApiErrorBody {
  code: string;
  message: string;
  retryable?: boolean;
  fields?: Record<string, unknown>;
  reasons?: { store_id?: number; store_name?: string; code: string; message: string }[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly fields: Record<string, unknown>;
  readonly reasons: NonNullable<ApiErrorBody["reasons"]>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.retryable = Boolean(body.retryable);
    this.fields = body.fields ?? {};
    this.reasons = body.reasons ?? [];
  }

  /** First field-level message, if the server sent any. */
  fieldMessage(name: string): string | undefined {
    const value = this.fields[name];
    if (Array.isArray(value)) return String(value[0]);
    return typeof value === "string" ? value : undefined;
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method)) headers["X-CSRFToken"] = csrfToken();

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, {
      code: "NETWORK",
      message: "Could not reach ZuuVi. Check your connection and try again.",
      retryable: true,
    });
  }

  if (response.status === 204) return undefined as T;
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const err = (data as { error?: ApiErrorBody } | null)?.error;
    throw new ApiError(
      response.status,
      err ?? { code: "REQUEST_ERROR", message: "Something went wrong. Please try again." },
    );
  }
  return data as T;
}

export const get = <T>(path: string) => api<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => api<T>("POST", path, body ?? {});
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const del = (path: string) => api<void>("DELETE", path);

/** Plain-language text for any thrown value. Never shows raw error objects. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}
