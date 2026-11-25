import { describe, expect, it } from 'vitest'
import { formatPrice } from './format'

describe('formatPrice', () => {
  it('shows bolivianos (Bs) with a decimal comma and no conversion', () => {
    expect(formatPrice(25.5)).toMatch(/^Bs\s25,50$/)
    expect(formatPrice(0)).toMatch(/^Bs\s0,00$/)
  })

  it('groups thousands with a dot', () => {
    expect(formatPrice(1234.5)).toMatch(/^Bs\s1\.234,50$/)
  })
})
