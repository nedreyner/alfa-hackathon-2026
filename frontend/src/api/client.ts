import createClient from 'openapi-fetch';

import type { paths } from './schema';

export const api = createClient<paths>({ baseUrl: '', credentials: 'include' });

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: unknown };
}

let onUnauthorized: () => void = () => {
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login'))
    window.location.assign('/login');
};

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

/** Ответ openapi-fetch → данные или ApiError; 401 на защищённых эндпоинтах уводит на вход. */
export function unwrap<T>(
  res: { data?: T; error?: unknown; response: Response },
  opts: { allow401?: boolean } = {},
): T {
  if (res.error !== undefined || !res.response.ok) {
    const body = (res.error ?? {}) as ErrorBody;
    const status = res.response.status;
    if (status === 401 && !opts.allow401) onUnauthorized();
    throw new ApiError(
      status,
      body.error?.code ?? 'internal',
      body.error?.message ?? 'Ошибка запроса',
      body.error?.details,
    );
  }
  return res.data as T;
}

export function isApiError(e: unknown, code?: string): e is ApiError {
  return e instanceof ApiError && (code === undefined || e.code === code);
}
