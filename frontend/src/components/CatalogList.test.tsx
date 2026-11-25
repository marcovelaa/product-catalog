import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Product } from '../api/catalog'
import { CatalogList } from './CatalogList'

const product = (id: number, name: string, price: number, stock: number): Product => ({
  id,
  name,
  price,
  stock,
  image_url: null,
  created_at: '2026-11-11T15:20:06Z',
})

const base = { products: [], slow: false, error: '', onRetry: () => {} }

describe('CatalogList', () => {
  it('shows a calm wake-up note when loading is slow', () => {
    render(<CatalogList {...base} status="loading" slow />)
    expect(screen.getByRole('status')).toHaveTextContent(/waking up the server/i)
  })

  it('shows the error with a retry button', () => {
    const onRetry = vi.fn()
    render(<CatalogList {...base} status="error" error="The server could not be reached." onRetry={onRetry} />)

    expect(screen.getByRole('alert')).toHaveTextContent('The server could not be reached.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('says so when the catalog is empty', () => {
    render(<CatalogList {...base} status="loaded" />)
    expect(screen.getByText(/catalog is empty/i)).toBeInTheDocument()
  })

  it('groups products by stock and formats prices', () => {
    render(
      <CatalogList
        {...base}
        status="loaded"
        products={[product(1, 'Wireless Mouse', 25.5, 12), product(2, 'Mechanical Keyboard', 89.99, 0)]}
      />,
    )

    expect(screen.getByText('2 products, 1 in stock.', { exact: false })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'In stock' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sold out' })).toBeInTheDocument()
    expect(screen.getByText('$25.50')).toBeInTheDocument()
    expect(screen.getByText('12 left')).toBeInTheDocument()
    expect(screen.getByText('$89.99')).toBeInTheDocument()
  })

  it('treats a negative stock as sold out so no row goes missing', () => {
    render(
      <CatalogList
        {...base}
        status="loaded"
        products={[product(1, 'Wireless Mouse', 25.5, 3), product(2, 'Broken Import', 10, -2)]}
      />,
    )

    expect(screen.getByText('2 products, 1 in stock.', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Broken Import')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sold out' })).toBeInTheDocument()
    expect(screen.getByText('None left')).toBeInTheDocument()
  })
})
