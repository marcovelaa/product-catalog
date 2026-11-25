import type { Product } from '../api/catalog'

const IN_STOCK_QUESTION = '¿Qué productos hay en stock ahora mismo?'

/** Up to three starter questions built from the real catalog. */
export function buildStarterQuestions(products: Product[]): string[] {
  if (products.length === 0) return [IN_STOCK_QUESTION, '¿Cuál es el producto más barato?']
  const byPrice = [...products].sort((a, b) => a.price - b.price)
  const cheapest = byPrice[0]
  const priciest = byPrice[byPrice.length - 1]
  const soldOut = products.find((product) => product.stock === 0)

  const questions = [IN_STOCK_QUESTION, `¿Cuántas unidades quedan de ${cheapest.name}?`]
  if (soldOut && soldOut !== cheapest) questions.push(`¿Está disponible el producto ${soldOut.name}?`)
  else if (priciest !== cheapest) questions.push(`¿Cuánto cuesta el producto ${priciest.name}?`)
  return questions
}
