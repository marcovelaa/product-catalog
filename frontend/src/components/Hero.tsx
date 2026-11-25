import { StripeBand } from './StripeBand'

interface HeroProps {
  statusUrl: string
  onAsk: () => void
}

export function Hero({ statusUrl, onAsk }: HeroProps) {
  return (
    <header className="hero">
      <StripeBand size="tall" />
      <div className="hero__body">
        <p className="wordmark rise" style={{ '--d': '0ms' } as React.CSSProperties}>
          Desk Catalog
        </p>
        <h1 className="hero__title lines">
          <span className="line">
            <span style={{ '--i': 0 } as React.CSSProperties}>Desk gear, with</span>
          </span>
          <span className="line">
            <span style={{ '--i': 1 } as React.CSSProperties}>answers attached</span>
          </span>
        </h1>
        <p className="hero__lead rise" style={{ '--d': '420ms' } as React.CSSProperties}>
          Browse every product with its live price and stock, or ask the assistant beside the list
          anything about what is on the shelf.
        </p>
        <button type="button" className="btn btn--accent rise" style={{ '--d': '480ms' } as React.CSSProperties} onClick={onAsk}>
          Ask a question
        </button>
      </div>
      <nav className="hero__links rise" style={{ '--d': '560ms' } as React.CSSProperties} aria-label="Page">
        <a className="link" href="#catalog">Catalog</a>
        <a className="link" href="#ask" onClick={(event) => { event.preventDefault(); onAsk() }}>
          Assistant
        </a>
        <a className="link" href={statusUrl}>Server status</a>
      </nav>
    </header>
  )
}
