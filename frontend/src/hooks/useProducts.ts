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

/** Server order is by id. The first list wins on a shared id; extras are appended. */
function mergeById(list: Product[], extras: Product[]): Product[] {
  const known = new Set(list.map((product) => product.id))
  return [...list, ...extras.filter((product) => !known.has(product.id))].sort((a, b) => a.id - b.id)
}

export function useProducts(load: typeof fetchProducts = fetchProducts) {
  const [state, setState] = useState<ProductsState>({
    status: 'loading',
    products: [],
    slow: false,
    error: '',
  })
  const controllerRef = useRef<AbortController | null>(null)
  // Products created in this session. A list that was requested before a creation finished
  // may not contain them yet, so they are merged back in whenever a list arrives.
  const addedRef = useRef<Product[]>([])

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
      setState({ status: 'loaded', products: mergeById(products, addedRef.current), slow: false, error: '' })
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'aborted') return
      setState((current) => ({ ...current, status: 'error', slow: false, error: describeError(error) }))
    }
  }, [load])

  /** Shows a product the server just created without reloading the whole list. */
  const addProduct = useCallback((product: Product) => {
    addedRef.current = mergeById(addedRef.current, [product])
    setState((current) => ({ ...current, products: mergeById(current.products, [product]) }))
  }, [])

  useEffect(() => {
    void reload()
    return () => controllerRef.current?.abort()
  }, [reload])

  return { ...state, reload, addProduct }
}
