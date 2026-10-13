// Thin fetch wrapper. Errors carry the server's `detail` so screens can show blockers and 409 reasons.

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(messageFor(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function messageFor(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const texts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
      return "";
    }).filter(Boolean);
    if (texts.length) return texts.join(" ");
  }
  if (detail && typeof detail === "object" && "blockers" in detail) {
    const blockers = (detail as { blockers: unknown }).blockers;
    if (Array.isArray(blockers) && blockers.length) return blockers.join(" ");
  }
  return `Request failed (${status})`;
}

async function request<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = data.detail ?? data;
    } catch {
      detail = await res.text().catch(() => null);
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T,>(path: string, body: unknown) => request<T>("PUT", path, body),
  delete: (path: string) => request<void>("DELETE", path),
};
