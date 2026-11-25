import { StripeBand } from './StripeBand'

export function SiteFooter() {
  return (
    <footer className="footer">
      <StripeBand size="thin" />
      <p className="footer__name">Desk Catalog</p>
      <p className="footer__note">
        Live prices and stock from the catalog API. The assistant answers only from this list.
      </p>
    </footer>
  )
}
