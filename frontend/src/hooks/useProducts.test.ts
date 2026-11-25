import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Product } from '../api/catalog'
import { deferred } from '../test/fetchMock'
import { useProducts } from './useProducts'

const product = (id: number, name = `Product ${id}`): Product => ({
  id,
  name,
  price: 10,
  stock: 1,
  image_url: null,
  created_at: '2026-11-24T10:00:00Z',
})

describe('useProducts.addProduct', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('inserts a created product in id order without duplicating it', async () => {
    const load = vi.fn().mockResolvedValue([product(1), product(3)])
    const { result } = renderHook(() => useProducts(load))
    await act(async () => {})

    act(() => result.current.addProduct(product(2)))
    expect(result.current.products.map((p) => p.id)).toEqual([1, 2, 3])

    act(() => result.current.addProduct(product(2)))
    expect(result.current.products.map((p) => p.id)).toEqual([1, 2, 3])
  })

  it('keeps a product added while a load is in flight once that older load resolves', async () => {
    const first = deferred<Product[]>()
    const load = vi.fn().mockReturnValue(first.promise)
    const { result } = renderHook(() => useProducts(load))

    act(() => result.current.addProduct(product(9, 'Fresh')))
    await act(async () => first.resolve([product(1)]))

    expect(result.current.status).toBe('loaded')
    expect(result.current.products.map((p) => p.id)).toEqual([1, 9])
  })

  it('does not duplicate a product that a later load also returns', async () => {
    const load = vi.fn().mockResolvedValueOnce([product(1)]).mockResolvedValueOnce([product(1), product(2)])
    const { result } = renderHook(() => useProducts(load))
    await act(async () => {})

    act(() => result.current.addProduct(product(2)))
    await act(async () => {
      await result.current.reload()
    })

    expect(result.current.products.map((p) => p.id)).toEqual([1, 2])
  })
})
