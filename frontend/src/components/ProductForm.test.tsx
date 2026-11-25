import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProductForm } from './ProductForm'

const base = {
  values: { name: '', price: '', stock: '0', imageUrl: '' },
  fieldErrors: {},
  status: 'idle' as const,
  slow: false,
  error: '',
  retryable: false,
  successMessage: '',
  onChange: () => {},
  onSubmit: () => {},
  onRetry: () => {},
}

describe('ProductForm', () => {
  it('has its own heading and labelled fields with numeric keyboards', () => {
    render(<ProductForm {...base} />)

    expect(screen.getByRole('heading', { name: 'Añadir un producto' })).toBeInTheDocument()
    expect(screen.getByLabelText('Nombre')).toBeRequired()
    expect(screen.getByLabelText('Precio (Bs)')).toHaveAttribute('inputmode', 'decimal')
    expect(screen.getByText('En bolivianos (Bs). Por ejemplo 25,50.')).toBeInTheDocument()
    expect(screen.getByLabelText('Stock')).toHaveAttribute('inputmode', 'numeric')
    expect(screen.getByLabelText('Enlace de imagen (opcional)')).toHaveAttribute('inputmode', 'url')
  })

  it('links each field error to its input with aria-describedby and marks it invalid', () => {
    render(
      <ProductForm
        {...base}
        fieldErrors={{ name: 'Escribe un nombre.', price: 'Escribe un precio.' }}
      />,
    )

    const name = screen.getByLabelText('Nombre')
    expect(name).toHaveAttribute('aria-invalid', 'true')
    const describedBy = name.getAttribute('aria-describedby') ?? ''
    const errorId = describedBy.split(' ').find((id) => document.getElementById(id)?.textContent === 'Escribe un nombre.')
    expect(errorId).toBeTruthy()

    expect(screen.getByLabelText('Precio (Bs)')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Stock')).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByText('Escribe un precio.')).toBeInTheDocument()
  })

  it('reports edits and submits through the form', () => {
    const onChange = vi.fn()
    const onSubmit = vi.fn()
    render(<ProductForm {...base} onChange={onChange} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Mouse' } })
    fireEvent.click(screen.getByRole('button', { name: 'Añadir producto' }))

    expect(onChange).toHaveBeenCalledWith('name', 'Mouse')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('disables the submit button and says so while submitting', () => {
    render(<ProductForm {...base} status="submitting" />)

    expect(screen.getByRole('button', { name: 'Añadiendo' })).toBeDisabled()
  })

  it('tells a waking server apart from a plain wait', () => {
    render(<ProductForm {...base} status="submitting" slow />)

    expect(screen.getByRole('status')).toHaveTextContent(/despertando/i)
  })

  it('shows a form-level server error and a retry button only when retrying is safe to offer', () => {
    const onRetry = vi.fn()
    const { rerender } = render(
      <ProductForm {...base} status="error" error="El servidor no respondió." retryable onRetry={onRetry} />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('El servidor no respondió.')
    fireEvent.click(screen.getByRole('button', { name: 'Intentar de nuevo' }))
    expect(onRetry).toHaveBeenCalledTimes(1)

    rerender(<ProductForm {...base} status="error" error="El servidor no aceptó el producto." />)
    expect(screen.getByRole('alert')).toHaveTextContent('no aceptó')
    expect(screen.queryByRole('button', { name: 'Intentar de nuevo' })).not.toBeInTheDocument()
  })

  it('announces the success message in a live region', () => {
    render(<ProductForm {...base} status="success" successMessage="Se añadió Wireless Mouse." />)

    expect(screen.getByRole('status')).toHaveTextContent('Se añadió Wireless Mouse.')
  })
})
