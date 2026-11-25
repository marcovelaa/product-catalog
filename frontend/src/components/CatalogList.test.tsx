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
    expect(screen.getByRole('status')).toHaveTextContent(/despertando el servidor/i)
  })

  it('shows the error with a retry button', () => {
    const onRetry = vi.fn()
    render(<CatalogList {...base} status="error" error="No se pudo conectar con el servidor." onRetry={onRetry} />)

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo conectar con el servidor.')
    fireEvent.click(screen.getByRole('button', { name: 'Intentar de nuevo' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('says so when the catalog is empty', () => {
    render(<CatalogList {...base} status="loaded" />)
    expect(screen.getByText(/catálogo está vacío/i)).toBeInTheDocument()
  })

  it('groups products by stock and formats prices', () => {
    render(
      <CatalogList
        {...base}
        status="loaded"
        products={[product(1, 'Wireless Mouse', 25.5, 12), product(2, 'Mechanical Keyboard', 89.99, 0)]}
      />,
    )

    expect(screen.getByText('2 productos, 1 en stock.', { exact: false })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'En stock' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Agotados' })).toBeInTheDocument()
    expect(screen.getByText(/^Bs\s25,50$/)).toBeInTheDocument()
    expect(screen.getByText('12 disponibles')).toBeInTheDocument()
    expect(screen.getByText(/^Bs\s89,99$/)).toBeInTheDocument()
  })

  it('treats a negative stock as sold out so no row goes missing', () => {
    render(
      <CatalogList
        {...base}
        status="loaded"
        products={[product(1, 'Wireless Mouse', 25.5, 3), product(2, 'Broken Import', 10, -2), product(3, 'Single Cable', 5, 1)]}
      />,
    )

    expect(screen.getByText('3 productos, 2 en stock.', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('1 disponible')).toBeInTheDocument()
    expect(screen.getByText('Broken Import')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Agotados' })).toBeInTheDocument()
    expect(screen.getByText('Agotado')).toBeInTheDocument()
  })
})
