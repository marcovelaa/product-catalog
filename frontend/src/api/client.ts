export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'validation' | 'aborted'

/** Every failure of requestJson is an ApiError, so callers switch on `kind`. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  readonly detail?: string

  constructor(kind: ApiErrorKind, options: { status?: number; detail?: string } = {}) {
    super(options.detail ?? kind)
    this.name = 'ApiError'
    this.kind = kind
    this.status = options.status
    this.detail = options.detail
  }
}

/** The Render free tier sleeps when idle; waking it can take about a minute. */
export const DEFAULT_BUDGET_MS = 75_000
export const DEFAULT_SLOW_AFTER_MS = 3_000
const DEFAULT_MAX_ATTEMPTS = 5
const DEFAULT_BASE_DELAY_MS = 1_000
const HTTP_UNPROCESSABLE = 422

export const API_BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

export interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  /** Lets the caller cancel, for example when a component unmounts. */
  signal?: AbortSignal
  /** Total deadline for all attempts and waits; the request is aborted after it. */
  budgetMs?: number
  /** Called once if the request is still unresolved after `slowAfterMs`. */
  onSlow?: () => void
  slowAfterMs?: number
  /** Attempts for network failures (no response at all). HTTP errors are never retried. */
  maxAttempts?: number
  baseDelayMs?: number
  baseUrl?: string
}

export async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    signal,
    budgetMs = DEFAULT_BUDGET_MS,
    onSlow,
    slowAfterMs = DEFAULT_SLOW_AFTER_MS,
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    baseDelayMs = DEFAULT_BASE_DELAY_MS,
    baseUrl = API_BASE_URL,
  } = options

  const controller = new AbortController()
  let timedOut = false
  const deadline = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, budgetMs)
  const slowTimer = onSlow ? setTimeout(onSlow, slowAfterMs) : undefined
  const forwardAbort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', forwardAbort, { once: true })

  const startedAt = Date.now()
  const abortError = () => new ApiError(timedOut ? 'timeout' : 'aborted')

  try {
    for (let attempt = 1; ; attempt += 1) {
      if (controller.signal.aborted) throw abortError()

      let response: Response
      try {
        response = await fetch(`${baseUrl}${path}`, {
          method,
          headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        })
      } catch {
        if (controller.signal.aborted) throw abortError()
        const delay = baseDelayMs * 2 ** (attempt - 1)
        const remaining = budgetMs - (Date.now() - startedAt)
        if (attempt >= maxAttempts || delay >= remaining) throw new ApiError('network')
        await wait(delay, controller.signal)
        continue
      }

      return await readResponse<T>(response, controller.signal, abortError)
    }
  } finally {
    clearTimeout(deadline)
    clearTimeout(slowTimer)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

async function readResponse<T>(
  response: Response,
  signal: AbortSignal,
  abortError: () => ApiError,
): Promise<T> {
  let data: unknown
  try {
    data = await response.json()
  } catch {
    if (signal.aborted) throw abortError()
    if (response.ok) throw new ApiError('http', { status: response.status, detail: 'Invalid JSON' })
  }
  if (response.ok) return data as T

  const kind = response.status === HTTP_UNPROCESSABLE ? 'validation' : 'http'
  throw new ApiError(kind, { status: response.status, detail: extractDetail(data) })
}

/** FastAPI sends `detail` as a string, or as a list of `{msg}` for validation errors. */
function extractDetail(data: unknown): string | undefined {
  if (typeof data !== 'object' || data === null || !('detail' in data)) return undefined
  const { detail } = data as { detail: unknown }
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first: unknown = detail[0]
    if (typeof first === 'object' && first !== null && 'msg' in first) {
      const { msg } = first as { msg: unknown }
      if (typeof msg === 'string') return msg
    }
  }
  return undefined
}

/** Resolves after `ms`, or early when the signal aborts (the caller re-checks it). */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms)
    signal.addEventListener('abort', done, { once: true })
    function done() {
      clearTimeout(timer)
      signal.removeEventListener('abort', done)
      resolve()
    }
  })
}
