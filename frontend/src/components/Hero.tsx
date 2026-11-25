interface HeroProps {
  statusUrl: string
  onAsk: () => void
}

export function Hero({ statusUrl, onAsk }: HeroProps) {
  return (
    <header className="hero">
      <div className="hero__body">
        <p className="wordmark rise" style={{ '--d': '0ms' } as React.CSSProperties}>
          Catálogo de escritorio
        </p>
        <h1 className="hero__title lines">
          <span className="line">
            <span style={{ '--i': 0 } as React.CSSProperties}>Accesorios para</span>
          </span>
          <span className="line">
            <span style={{ '--i': 1 } as React.CSSProperties}>tu escritorio</span>
          </span>
        </h1>
        <p className="hero__lead rise" style={{ '--d': '420ms' } as React.CSSProperties}>
          Consulta el precio y el stock de cada producto, o pregunta al asistente lo que quieras saber
          sobre el catálogo.
        </p>
        <button type="button" className="btn btn--accent rise" style={{ '--d': '480ms' } as React.CSSProperties} onClick={onAsk}>
          Pregunta al asistente
        </button>
      </div>
      <nav className="hero__links rise" style={{ '--d': '560ms' } as React.CSSProperties} aria-label="Página">
        <a className="link" href="#catalog">Catálogo</a>
        <a className="link" href="#ask" onClick={(event) => { event.preventDefault(); onAsk() }}>
          Asistente
        </a>
        <a className="link" href={statusUrl}>Estado del servidor</a>
      </nav>
    </header>
  )
}
