import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchProducts, type Product } from '../api/catalog'
import { ApiError } from '../api/client'
import { describeError } from '../api/messages'

export type ProductsStatus = 'loading' | 'loaded' | 'error'

export interface ProductsState {
  status: ProductsStatus
  products: Product[]
  /** Still loading after the slow threshold: the server is probably waking up. */
  slow: boolean
  error: string
}

export function useProducts(load: typeof fetchProducts = fetchProducts) {
  const [state, setState] = useState<ProductsState>({
    status: 'loading',
    products: [],
    slow: false,
    error: '',
  })
  const controllerRef = useRef<AbortController | null>(null)

  const reload = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setState((current) => ({ ...current, status: 'loading', slow: false, error: '' }))
    try {
      const products = await load({
        signal: controller.signal,
        onSlow: () => setState((current) => ({ ...current, slow: true })),
      })
      setState({ status: 'loaded', products, slow: false, error: '' })
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'aborted') return
      setState((current) => ({ ...current, status: 'error', slow: false, error: describeError(error) }))
    }
  }, [load])

  useEffect(() => {
    void reload()
    return () => controllerRef.current?.abort()
  }, [reload])

  return { ...state, reload }
}
