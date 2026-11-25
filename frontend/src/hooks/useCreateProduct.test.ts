import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Product } from '../api/catalog'
import { ApiError } from '../api/client'
import type { ProductFormValues } from '../lib/productInput'
import { deferred } from '../test/fetchMock'
import { useCreateProduct } from './useCreateProduct'

const values: ProductFormValues = { name: ' Wireless Mouse ', price: '25.50', stock: '12', imageUrl: '' }

const created: Product = {
  id: 7,
  name: 'Wireless Mouse',
  price: 25.5,
  stock: 12,
  image_url: null,
  created_at: '2026-11-24T10:00:00Z',
}

describe('useCreateProduct', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('goes idle, submitting, success and reports the created product', async () => {
    const response = deferred<Product>()
    const create = vi.fn().mockReturnValue(response.promise)
    const onCreated = vi.fn()
    const { result } = renderHook(() => useCreateProduct({ create, onCreated }))
    expect(result.current.status).toBe('idle')

    act(() => {
      expect(result.current.submit(values)).toEqual({ kind: 'started' })
    })
    expect(result.current.status).toBe('submitting')
    expect(create).toHaveBeenCalledWith(
      { name: 'Wireless Mouse', price: 25.5, stock: 12, image_url: null },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    await act(async () => response.resolve(created))

    expect(result.current.status).toBe('success')
    expect(result.current.created).toEqual(created)
    expect(onCreated).toHaveBeenCalledWith(created)
  })

  it('validates first: invalid input never reaches the server and names the first bad field', () => {
    const create = vi.fn()
    const { result } = renderHook(() => useCreateProduct({ create }))

    act(() => {
      expect(result.current.submit({ ...values, name: '', price: 'abc' })).toEqual({
        kind: 'invalid',
        field: 'name',
      })
    })

    expect(create).not.toHaveBeenCalled()
    expect(result.current.status).toBe('idle')
    expect(result.current.fieldErrors).toEqual({
      name: 'Enter a name.',
      price: 'Enter a number, for example 25.50.',
    })
  })

  it('clears one field error when the visitor edits that field', () => {
    const { result } = renderHook(() => useCreateProduct({ create: vi.fn() }))
    act(() => {
      result.current.submit({ ...values, name: '', price: '' })
    })

    act(() => result.current.clearFieldError('name'))

    expect(result.current.fieldErrors).toEqual({ price: 'Enter a price.' })
  })

  it('shows a 422 from the server as a form-level error that cannot simply be retried', async () => {
    const create = vi
      .fn()
      .mockRejectedValue(new ApiError('validation', { status: 422, detail: 'String should have at most 200 characters' }))
    const onCreated = vi.fn()
    const { result } = renderHook(() => useCreateProduct({ create, onCreated }))

    await act(async () => {
      result.current.submit(values)
    })

    expect(result.current.status).toBe('error')
    expect(result.current.error).toContain('String should have at most 200 characters')
    expect(result.current.retryable).toBe(false)
    expect(result.current.fieldErrors).toEqual({})
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('shows a calm, retryable message on a network failure and allows a manual second attempt', async () => {
    const create = vi.fn().mockRejectedValueOnce(new ApiError('network')).mockResolvedValueOnce(created)
    const { result } = renderHook(() => useCreateProduct({ create }))

    await act(async () => {
      result.current.submit(values)
    })

    expect(result.current.status).toBe('error')
    expect(result.current.error).toMatch(/waking up/i)
    expect(result.current.retryable).toBe(true)
    expect(create).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.submit(values)
    })

    expect(create).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('success')
    expect(result.current.error).toBe('')
  })

  it('ignores a second submit while one is in flight', () => {
    const create = vi.fn().mockReturnValue(deferred<Product>().promise)
    const { result } = renderHook(() => useCreateProduct({ create }))

    act(() => {
      result.current.submit(values)
    })
    let second: ReturnType<typeof result.current.submit> | undefined
    act(() => {
      second = result.current.submit(values)
    })

    expect(second).toEqual({ kind: 'busy' })
    expect(create).toHaveBeenCalledTimes(1)
  })

  it('flags a slow request after the slow threshold', async () => {
    const create = vi.fn().mockImplementation(async (_input, options) => {
      options.onSlow()
      return new Promise<Product>(() => {})
    })
    const { result } = renderHook(() => useCreateProduct({ create }))

    await act(async () => {
      result.current.submit(values)
    })

    expect(result.current.slow).toBe(true)
  })

  it('aborts the request in flight when unmounted', () => {
    const create = vi.fn().mockReturnValue(deferred<Product>().promise)
    const { result, unmount } = renderHook(() => useCreateProduct({ create }))

    act(() => {
      result.current.submit(values)
    })
    unmount()

    expect(create.mock.calls[0][1].signal.aborted).toBe(true)
  })
})
