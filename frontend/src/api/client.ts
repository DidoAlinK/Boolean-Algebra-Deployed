import type {
  AnalyzeRequest, AnalyzeResponse, SynthesizeRequest, ApiError, ApiErrorEnvelope, HealthResponse, Preset,
  RuleInfo, SimplifyRequest, SimplifyResponse,
} from './types';

// VITE_API_URL wins when set (split deploy). Otherwise: dev server -> local backend, production build -> same origin
// (the backend serves the built frontend, so '/api/...' just works).
const API_BASE_URL = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/+$/, '');

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: ApiError['code'] | 'network_error';
  readonly position?: number;
  /** Seconds to wait before retrying (rate limit, busy server). */
  readonly retryAfter?: number;

  constructor(message: string, status: number, code: ApiError['code'] | 'network_error', position?: number, retryAfter?: number) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
    this.position = position;
    this.retryAfter = retryAfter;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiClientError('NO CONNECTION TO DRAFTING SERVER', 0, 'network_error');
  }

  if (!response.ok) {
    let payload: ApiErrorEnvelope | null = null;
    try { payload = await response.json() as ApiErrorEnvelope; } catch { /* undocumented response */ }
    const apiError = payload?.error;
    if (apiError) {
      const headerWait = Number(response.headers.get('Retry-After'));
      const retryAfter = apiError.retry_after ?? (Number.isFinite(headerWait) && headerWait > 0 ? headerWait : undefined);
      throw new ApiClientError(apiError.message, response.status, apiError.code, apiError.position, retryAfter);
    }
    throw new ApiClientError(`SERVER ERROR: ${response.status}`, response.status, 'network_error');
  }
  return await response.json() as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/api/health', { signal }),
  getPresets: (signal?: AbortSignal) => request<Preset[]>('/api/presets', { signal }),
  validatePreset: (preset: Preset, signal?: AbortSignal) =>
    request<Preset>('/api/presets/validate', { method: 'POST', body: JSON.stringify(preset), signal }),
  analyze: (payload: AnalyzeRequest, signal?: AbortSignal) =>
    request<AnalyzeResponse>('/api/analyze', { method: 'POST', body: JSON.stringify(payload), signal }),
  synthesize: (payload: SynthesizeRequest, signal?: AbortSignal) =>
    request<AnalyzeResponse>('/api/synthesize', { method: 'POST', body: JSON.stringify(payload), signal }),
  simplify: (payload: SimplifyRequest, signal?: AbortSignal) =>
    request<SimplifyResponse>('/api/simplify', { method: 'POST', body: JSON.stringify(payload), signal }),
  simplifyRules: (signal?: AbortSignal) => request<RuleInfo[]>('/api/simplify/rules', { signal }),
};

export { API_BASE_URL };
