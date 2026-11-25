import type { FormEvent } from 'react'
import type { CreateStatus } from '../hooks/useCreateProduct'
import type { FieldErrors, ProductField, ProductFormValues } from '../lib/productInput'

interface ProductFormProps {
  values: ProductFormValues
  fieldErrors: FieldErrors
  status: CreateStatus
  /** Still saving after the slow threshold: the server is probably waking up. */
  slow: boolean
  /** Form-level message for a failed request, such as a 422 from the server. */
  error: string
  /** Offer a manual retry: the failure left it unknown whether the product was saved. */
  retryable: boolean
  successMessage: string
  onChange: (field: ProductField, value: string) => void
  onSubmit: () => void
  onRetry: () => void
}

export function fieldId(field: ProductField): string {
  return `product-${field}`
}

export function ProductForm({
  values,
  fieldErrors,
  status,
  slow,
  error,
  retryable,
  successMessage,
  onChange,
  onSubmit,
  onRetry,
}: ProductFormProps) {
  const isSubmitting = status === 'submitting'

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSubmit()
  }

  const field = { values, fieldErrors, onChange }

  return (
    <section id="add-product" className="add" aria-labelledby="add-title">
      <h2 id="add-title" className="section-title">Añadir un producto</h2>

      <form className="add__form" noValidate aria-busy={isSubmitting} onSubmit={handleSubmit}>
        <Field {...field} name="name" label="Nombre" required autoComplete="off" />

        <div className="add__pair">
          <Field
            {...field}
            name="price"
            label="Precio"
            hint="Por ejemplo 25,50."
            required
            inputMode="decimal"
            autoComplete="off"
          />
          <Field
            {...field}
            name="stock"
            label="Stock"
            hint="Unidades disponibles. Vacío equivale a 0."
            inputMode="numeric"
            autoComplete="off"
          />
        </div>

        <Field
          {...field}
          name="imageUrl"
          label="Enlace de imagen (opcional)"
          hint="Empieza con http:// o https://."
          type="url"
          inputMode="url"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
        />

        {error && (
          <div className="form-error" role="alert">
            <p>{error}</p>
            {retryable && (
              <button type="button" className="btn btn--ink" onClick={onRetry} disabled={isSubmitting}>
                Intentar de nuevo
              </button>
            )}
          </div>
        )}

        <div className="add__actions">
          <button type="submit" className="btn btn--accent" disabled={isSubmitting}>
            {isSubmitting ? 'Añadiendo' : 'Añadir producto'}
          </button>
        </div>

        <div className="add__status" role="status">
          {isSubmitting && slow && (
            <p className="form-note">Guardando. El servidor está despertando, así que puede tardar hasta un minuto.</p>
          )}
          {successMessage && <p className="form-note">{successMessage}</p>}
        </div>
      </form>
    </section>
  )
}

interface FieldProps {
  name: ProductField
  label: string
  hint?: string
  values: ProductFormValues
  fieldErrors: FieldErrors
  onChange: (field: ProductField, value: string) => void
  required?: boolean
  type?: 'text' | 'url'
  inputMode?: 'decimal' | 'numeric' | 'url'
  autoComplete?: string
  autoCapitalize?: string
  spellCheck?: boolean
}

function Field({ name, label, hint, values, fieldErrors, onChange, type = 'text', ...inputProps }: FieldProps) {
  const id = fieldId(name)
  const message = fieldErrors[name]
  const describedBy = [hint ? `${id}-hint` : '', message ? `${id}-error` : ''].filter(Boolean).join(' ')

  return (
    <div className="field">
      <label htmlFor={id} className="field__label">
        {label}
      </label>
      <input
        {...inputProps}
        id={id}
        type={type}
        className="field__input"
        value={values[name]}
        aria-invalid={Boolean(message)}
        aria-describedby={describedBy || undefined}
        onChange={(event) => onChange(name, event.target.value)}
      />
      {hint && (
        <p id={`${id}-hint`} className="field__hint">
          {hint}
        </p>
      )}
      {message && (
        <p id={`${id}-error`} className="field__error">
          {message}
        </p>
      )}
    </div>
  )
}
