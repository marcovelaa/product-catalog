import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { hangingFetch, jsonResponse, networkError, stubFetch } from '../test/fetchMock'
import { createProduct } from './catalog'
import type { ApiError } from './client'

const input = { name: 'Wireless Mouse', price: 25.5, stock: 12, image_url: null }

describe('createProduct', () => {
  let fetchMock: ReturnType<typeof stubFetch>

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = stubFetch()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('POSTs the product as JSON and returns the created product', async () => {
    const created = { id: 7, ...input, created_at: '2026-11-24T10:00:00Z' }
    fetchMock.mockResolvedValue(jsonResponse(created, 201))

    await expect(createProduct(input)).resolves.toEqual(created)

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/v1\/products$/)
    expect(init?.method).toBe('POST')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(init?.body))).toEqual(input)
  })

  it('attempts a failed POST exactly once: it is not idempotent, so it must never be retried', async () => {
    fetchMock.mockRejectedValue(networkError())

    const result = createProduct(input).catch((error: ApiError) => error)
    await vi.advanceTimersByTimeAsync(60_000)

    expect(await result).toMatchObject({ kind: 'network' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not resend after a timeout either', async () => {
    fetchMock.mockImplementation(hangingFetch())

    const result = createProduct(input).catch((error: ApiError) => error)
    await vi.advanceTimersByTimeAsync(80_000)

    expect(await result).toMatchObject({ kind: 'timeout' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('surfaces a 422 as a validation error', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'Input should be greater than or equal to 0' }] }, 422),
    )

    const error = await createProduct(input).catch((e: ApiError) => e)

    expect(error).toMatchObject({ kind: 'validation', status: 422 })
  })
})
