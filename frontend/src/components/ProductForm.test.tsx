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

    expect(screen.getByRole('heading', { name: 'Add a product' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeRequired()
    expect(screen.getByLabelText('Price')).toHaveAttribute('inputmode', 'decimal')
    expect(screen.getByLabelText('Stock')).toHaveAttribute('inputmode', 'numeric')
    expect(screen.getByLabelText('Image link (optional)')).toHaveAttribute('inputmode', 'url')
  })

  it('links each field error to its input with aria-describedby and marks it invalid', () => {
    render(
      <ProductForm
        {...base}
        fieldErrors={{ name: 'Enter a name.', price: 'Enter a price.' }}
      />,
    )

    const name = screen.getByLabelText('Name')
    expect(name).toHaveAttribute('aria-invalid', 'true')
    const describedBy = name.getAttribute('aria-describedby') ?? ''
    const errorId = describedBy.split(' ').find((id) => document.getElementById(id)?.textContent === 'Enter a name.')
    expect(errorId).toBeTruthy()

    expect(screen.getByLabelText('Price')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Stock')).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByText('Enter a price.')).toBeInTheDocument()
  })

  it('reports edits and submits through the form', () => {
    const onChange = vi.fn()
    const onSubmit = vi.fn()
    render(<ProductForm {...base} onChange={onChange} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Mouse' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add product' }))

    expect(onChange).toHaveBeenCalledWith('name', 'Mouse')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('disables the submit button and says so while submitting', () => {
    render(<ProductForm {...base} status="submitting" />)

    expect(screen.getByRole('button', { name: 'Adding' })).toBeDisabled()
  })

  it('tells a waking server apart from a plain wait', () => {
    render(<ProductForm {...base} status="submitting" slow />)

    expect(screen.getByRole('status')).toHaveTextContent(/waking up/i)
  })

  it('shows a form-level server error and a retry button only when retrying is safe to offer', () => {
    const onRetry = vi.fn()
    const { rerender } = render(
      <ProductForm {...base} status="error" error="The server did not answer." retryable onRetry={onRetry} />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('The server did not answer.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledTimes(1)

    rerender(<ProductForm {...base} status="error" error="The server did not accept the product." />)
    expect(screen.getByRole('alert')).toHaveTextContent('did not accept')
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('announces the success message in a live region', () => {
    render(<ProductForm {...base} status="success" successMessage="Added Wireless Mouse." />)

    expect(screen.getByRole('status')).toHaveTextContent('Added Wireless Mouse.')
  })
})
