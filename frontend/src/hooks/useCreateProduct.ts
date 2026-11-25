import { useCallback, useEffect, useRef, useState } from 'react'
import { createProduct, type Product } from '../api/catalog'
import { ApiError } from '../api/client'
import { describeCreateError } from '../api/messages'
import {
  PRODUCT_FIELDS,
  parseProductForm,
  type FieldErrors,
  type ProductField,
  type ProductFormValues,
} from '../lib/productInput'

export type CreateStatus = 'idle' | 'submitting' | 'success' | 'error'

export type SubmitOutcome =
  | { kind: 'started' }
  | { kind: 'busy' }
  /** Client-side validation failed; `field` is the first invalid field on screen. */
  | { kind: 'invalid'; field: ProductField }

interface CreateState {
  status: CreateStatus
  fieldErrors: FieldErrors
  /** Form-level message for a failed request. */
  error: string
  /** The failure left it unknown whether the product was saved, so a manual retry is offered. */
  retryable: boolean
  /** Still waiting after the slow threshold: the server is probably waking up. */
  slow: boolean
  created: Product | null
}

const INITIAL: CreateState = {
  status: 'idle',
  fieldErrors: {},
  error: '',
  retryable: false,
  slow: false,
  created: null,
}

interface UseCreateProductOptions {
  create?: typeof createProduct
  onCreated?: (product: Product) => void
}

export function useCreateProduct({ create = createProduct, onCreated }: UseCreateProductOptions = {}) {
  const [state, setState] = useState<CreateState>(INITIAL)
  const busyRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)
  const onCreatedRef = useRef(onCreated)

  useEffect(() => {
    onCreatedRef.current = onCreated
  }, [onCreated])

  useEffect(() => () => controllerRef.current?.abort(), [])

  const submit = useCallback(
    (values: ProductFormValues): SubmitOutcome => {
      if (busyRef.current) return { kind: 'busy' }

      const parsed = parseProductForm(values)
      if (!parsed.ok) {
        setState((current) => ({ ...current, status: 'idle', fieldErrors: parsed.errors, error: '', retryable: false }))
        const field = PRODUCT_FIELDS.find((name) => parsed.errors[name]) ?? 'name'
        return { kind: 'invalid', field }
      }

      busyRef.current = true
      const controller = new AbortController()
      controllerRef.current = controller
      setState({ ...INITIAL, status: 'submitting' })

      create(parsed.input, {
        signal: controller.signal,
        onSlow: () => setState((current) => ({ ...current, slow: true })),
      })
        .then((product) => {
          setState({ ...INITIAL, status: 'success', created: product })
          onCreatedRef.current?.(product)
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.kind === 'aborted') return
          const retryable = error instanceof ApiError && (error.kind === 'network' || error.kind === 'timeout')
          setState({ ...INITIAL, status: 'error', error: describeCreateError(error), retryable })
        })
        .finally(() => {
          if (controllerRef.current === controller) controllerRef.current = null
          busyRef.current = false
        })

      return { kind: 'started' }
    },
    [create],
  )

  const clearFieldError = useCallback((field: ProductField) => {
    setState((current) => {
      if (!current.fieldErrors[field]) return current
      const { [field]: _removed, ...rest } = current.fieldErrors
      return { ...current, fieldErrors: rest }
    })
  }, [])

  /** Back to idle, for example when the visitor starts typing after a success. */
  const dismiss = useCallback(() => {
    setState((current) => (current.status === 'success' ? INITIAL : current))
  }, [])

  return { ...state, submit, clearFieldError, dismiss }
}
