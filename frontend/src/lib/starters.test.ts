import { describe, expect, it } from 'vitest'
import type { Product } from '../api/catalog'
import { buildStarterQuestions } from './starters'

const product = (id: number, name: string, price: number, stock: number): Product => ({
  id,
  name,
  price,
  stock,
  image_url: null,
  created_at: '2026-11-11T15:20:06Z',
})

describe('buildStarterQuestions', () => {
  it('falls back to general questions without products', () => {
    expect(buildStarterQuestions([])).toHaveLength(2)
  })

  it('names the cheapest and a sold-out product from the catalog', () => {
    const questions = buildStarterQuestions([
      product(1, 'Wireless Mouse', 25.5, 12),
      product(2, 'Mechanical Keyboard', 89.99, 0),
      product(3, 'USB-C Hub', 34.9, 12),
    ])

    expect(questions).toEqual([
      'Which products are in stock right now?',
      'How many Wireless Mouse units are left?',
      'Is the Mechanical Keyboard available?',
    ])
  })

  it('asks about the most expensive product when nothing is sold out', () => {
    const questions = buildStarterQuestions([product(1, 'Mouse', 10, 1), product(2, 'Stand', 40, 2)])
    expect(questions[2]).toBe('What does the Stand cost?')
  })
})
