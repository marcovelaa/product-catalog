import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { hangingFetch, jsonResponse, networkError, stubFetch } from '../test/fetchMock'
import { ApiError, requestJson } from './client'

const BASE = 'https://api.test'

async function settle<T>(promise: Promise<T>): Promise<T | ApiError> {
  return promise.catch((error: ApiError) => error)
}

describe('requestJson', () => {
  let fetchMock: ReturnType<typeof stubFetch>

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = stubFetch()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('returns the parsed JSON body on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 1 }]))

    await expect(requestJson('/api/v1/products', { baseUrl: BASE })).resolves.toEqual([{ id: 1 }])
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.test/api/v1/products',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('sends a JSON body on POST', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ answer: 'Yes' }))

    await requestJson('/ask', { baseUrl: BASE, method: 'POST', body: { question: 'Hi?' } })

    const init = fetchMock.mock.calls[0][1]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe('{"question":"Hi?"}')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
  })

  it('maps a 422 to a validation error with the first detail message', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'String should have at most 500 characters' }] }, 422),
    )

    const error = await settle(requestJson('/ask', { baseUrl: BASE }))

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      kind: 'validation',
      status: 422,
      detail: 'String should have at most 500 characters',
    })
  })

  it('maps other non-2xx responses to an http error and does not retry them', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'quota exceeded' }, 429))

    const error = await settle(requestJson('/ask', { baseUrl: BASE }))

    expect(error).toMatchObject({ kind: 'http', status: 429, detail: 'quota exceeded' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries network failures with exponential backoff and then succeeds', async () => {
    fetchMock
      .mockRejectedValueOnce(networkError())
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce(jsonResponse({ status: 'ok' }))

    const result = requestJson('/health', { baseUrl: BASE, baseDelayMs: 1000 })

    await vi.advanceTimersByTimeAsync(999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    await expect(result).resolves.toEqual({ status: 'ok' })
  })

  it('gives up with a network error after the maximum number of attempts', async () => {
    fetchMock.mockRejectedValue(networkError())

    const result = settle(requestJson('/health', { baseUrl: BASE, maxAttempts: 3, baseDelayMs: 100 }))
    await vi.advanceTimersByTimeAsync(10_000)

    expect(await result).toMatchObject({ kind: 'network' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('never schedules a retry beyond the total time budget', async () => {
    fetchMock.mockRejectedValue(networkError())

    const result = settle(
      requestJson('/health', { baseUrl: BASE, budgetMs: 5000, baseDelayMs: 2000, maxAttempts: 10 }),
    )
    await vi.advanceTimersByTimeAsync(5000)

    // Attempts at 0 s and 2 s; the next delay (4 s) would end past the 5 s budget.
    expect(await result).toMatchObject({ kind: 'network' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('aborts the request and reports a timeout when the budget runs out', async () => {
    fetchMock.mockImplementation(hangingFetch())

    const result = settle(requestJson('/api/v1/products', { baseUrl: BASE, budgetMs: 75_000 }))
    await vi.advanceTimersByTimeAsync(74_999)
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)

    expect(await result).toMatchObject({ kind: 'timeout' })
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true)
  })

  it('reports a slow request once it has not resolved after the slow threshold', async () => {
    fetchMock.mockImplementation(hangingFetch())
    const onSlow = vi.fn()

    const result = settle(requestJson('/api/v1/products', { baseUrl: BASE, onSlow, budgetMs: 10_000 }))
    await vi.advanceTimersByTimeAsync(2999)
    expect(onSlow).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(onSlow).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(10_000)
    await result
  })

  it('does not report a slow request that resolved in time', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]))
    const onSlow = vi.fn()

    await requestJson('/api/v1/products', { baseUrl: BASE, onSlow })
    await vi.advanceTimersByTimeAsync(5000)

    expect(onSlow).not.toHaveBeenCalled()
  })

  it('reports a caller abort as aborted, not as a timeout or network error', async () => {
    fetchMock.mockImplementation(hangingFetch())
    const controller = new AbortController()

    const result = settle(requestJson('/api/v1/products', { baseUrl: BASE, signal: controller.signal }))
    controller.abort()

    expect(await result).toMatchObject({ kind: 'aborted' })
  })
})
