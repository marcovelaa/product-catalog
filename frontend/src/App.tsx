import { useRef, useState } from 'react'
import { API_BASE_URL } from './api/client'
import { CatalogList } from './components/CatalogList'
import { Hero } from './components/Hero'
import { SiteFooter } from './components/SiteFooter'
import { ChatContainer } from './containers/ChatContainer'
import { ProductFormContainer } from './containers/ProductFormContainer'
import { useProducts } from './hooks/useProducts'

type Tab = 'catalog' | 'ask'

export function App() {
  const catalog = useProducts()
  const [tab, setTab] = useState<Tab>('catalog')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  function openChat() {
    setTab('ask')
    // Wait for the phone layout to reveal the panel before moving focus into it.
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  return (
    <div className="page">
      <main className="page__read" data-tab-active={tab === 'catalog'}>
        <article className="card">
          <Hero statusUrl={`${API_BASE_URL}/health`} onAsk={openChat} />
          <CatalogList
            status={catalog.status}
            products={catalog.products}
            slow={catalog.slow}
            error={catalog.error}
            onRetry={catalog.reload}
          />
          <ProductFormContainer onCreated={catalog.addProduct} />
          <SiteFooter />
        </article>
      </main>

      <aside className="page__chat" data-tab-active={tab === 'ask'} aria-label="Catalog assistant">
        <ChatContainer products={catalog.products} inputRef={inputRef} />
      </aside>

      <nav className="tabs" aria-label="Sections">
        <button type="button" className="tabs__tab" aria-pressed={tab === 'catalog'} onClick={() => setTab('catalog')}>
          Catalog
        </button>
        <button type="button" className="tabs__tab" aria-pressed={tab === 'ask'} onClick={() => setTab('ask')}>
          Ask
        </button>
      </nav>
    </div>
  )
}
