import type { Product } from '../api/catalog'

const IN_STOCK_QUESTION = 'Which products are in stock right now?'

/** Up to three starter questions built from the real catalog. */
export function buildStarterQuestions(products: Product[]): string[] {
  if (products.length === 0) return [IN_STOCK_QUESTION, 'What is the cheapest product?']
  const byPrice = [...products].sort((a, b) => a.price - b.price)
  const cheapest = byPrice[0]
  const priciest = byPrice[byPrice.length - 1]
  const soldOut = products.find((product) => product.stock === 0)

  const questions = [IN_STOCK_QUESTION, `How many ${cheapest.name} units are left?`]
  if (soldOut && soldOut !== cheapest) questions.push(`Is the ${soldOut.name} available?`)
  else if (priciest !== cheapest) questions.push(`What does the ${priciest.name} cost?`)
  return questions
}
