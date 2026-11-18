// The API error type and its message helper. There is no shared fetch wrapper:
// every call in this app is a raw fetch against a tokenized path (see
// apps/todo-gtd/api.ts).

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * The server's own `detail` string when there is one, so a 400 shows the
 * sentence the service wrote rather than the "API error 400: …" wrapper.
 */
export function apiErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError && typeof e.detail === 'string' && e.detail.trim() !== '') {
    return e.detail;
  }
  return e instanceof Error ? e.message : fallback;
}
