import type { Product } from '../api/catalog'
import type { ProductsStatus } from '../hooks/useProducts'
import { formatPrice } from '../lib/format'

/** Long lists would otherwise leave late rows (or a newly added one) invisible for seconds. */
const MAX_STAGGER = 8

interface CatalogListProps {
  status: ProductsStatus
  products: Product[]
  slow: boolean
  error: string
  onRetry: () => void
}

export function CatalogList({ status, products, slow, error, onRetry }: CatalogListProps) {
  const inStock = products.filter((product) => product.stock > 0)
  const soldOut = products.filter((product) => product.stock <= 0)

  return (
    <section id="catalog" className="catalog" aria-labelledby="catalog-title" aria-busy={status === 'loading'}>
      <h2 id="catalog-title" className="section-title">The catalog</h2>

      {status === 'loading' && (
        <p className="catalog__note" role="status">
          {slow
            ? 'Waking up the server. The first visit after a quiet spell can take up to a minute.'
            : 'Loading the catalog.'}
        </p>
      )}

      {status === 'error' && (
        <div className="catalog__note" role="alert">
          <p>{error}</p>
          <button type="button" className="btn btn--accent" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {status === 'loaded' && products.length === 0 && (
        <p className="catalog__note">The catalog is empty for now. New products will show up here.</p>
      )}

      {status === 'loaded' && products.length > 0 && (
        <>
          <p className="catalog__note">
            {products.length} {products.length === 1 ? 'product' : 'products'}, {inStock.length} in
            stock. Prices and stock come straight from the live catalog.
          </p>
          <ProductGroup label="In stock" products={inStock} offset={0} />
          <ProductGroup label="Sold out" products={soldOut} offset={inStock.length} />
        </>
      )}
    </section>
  )
}

function ProductGroup({ label, products, offset }: { label: string; products: Product[]; offset: number }) {
  if (products.length === 0) return null
  return (
    <div className="catalog__group">
      <h3 className="catalog__group-label">{label}</h3>
      <ul className="catalog__rows">
        {products.map((product, index) => (
          <li key={product.id} className="row" style={{ '--i': Math.min(offset + index, MAX_STAGGER) } as React.CSSProperties}>
            <span className="row__name">
              <span className={`row__dot ${product.stock > 0 ? 'row__dot--in' : ''}`} aria-hidden="true" />
              {product.name}
            </span>
            <span className="row__value">
              <span className="row__stock">{product.stock > 0 ? `${product.stock} left` : 'None left'}</span>
              <span className="row__price">{formatPrice(product.price)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
