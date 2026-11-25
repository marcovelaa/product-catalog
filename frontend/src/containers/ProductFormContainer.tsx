import { useEffect, useRef, useState } from 'react'
import type { Product } from '../api/catalog'
import { fieldId, ProductForm } from '../components/ProductForm'
import { useCreateProduct } from '../hooks/useCreateProduct'
import { EMPTY_PRODUCT_FORM, type ProductField } from '../lib/productInput'

interface ProductFormContainerProps {
  /** Called with the product the server created, so the list can show it. */
  onCreated: (product: Product) => void
}

export function ProductFormContainer({ onCreated }: ProductFormContainerProps) {
  const [values, setValues] = useState(EMPTY_PRODUCT_FORM)
  const create = useCreateProduct({
    onCreated: (product) => {
      setValues(EMPTY_PRODUCT_FORM)
      onCreated(product)
    },
  })
  const wasSubmitting = useRef(false)

  // The submit button is disabled while saving, which drops focus to the page. Put it back
  // in the form afterwards, unless the visitor has already moved on to something else.
  useEffect(() => {
    const finished = wasSubmitting.current && create.status !== 'submitting'
    wasSubmitting.current = create.status === 'submitting'
    if (finished && document.activeElement === document.body) focusField('name')
  }, [create.status])

  function handleChange(field: ProductField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    create.clearFieldError(field)
    create.dismiss()
  }

  function submit() {
    const outcome = create.submit(values)
    if (outcome.kind === 'invalid') focusField(outcome.field)
  }

  return (
    <ProductForm
      values={values}
      fieldErrors={create.fieldErrors}
      status={create.status}
      slow={create.slow}
      error={create.error}
      retryable={create.retryable}
      successMessage={create.status === 'success' && create.created ? `Added ${create.created.name}.` : ''}
      onChange={handleChange}
      onSubmit={submit}
      onRetry={submit}
    />
  )
}

function focusField(field: ProductField) {
  document.getElementById(fieldId(field))?.focus()
}
