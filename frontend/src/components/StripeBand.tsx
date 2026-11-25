const BAR_COUNT = 64

/** The card's one ornament: alternating 28px bars of ink and paper, built as filled blocks. */
export function StripeBand({ size }: { size: 'tall' | 'thin' }) {
  return (
    <div className={`stripe stripe--${size}`} aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, index) => (
        <span key={index} className="stripe__bar" style={{ '--i': index } as React.CSSProperties} />
      ))}
    </div>
  )
}
