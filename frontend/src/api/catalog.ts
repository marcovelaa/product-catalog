import { requestJson, type RequestOptions } from './client'

/** Mirrors backend schemas.ProductResponse. */
export interface Product {
  id: number
  name: string
  price: number
  stock: number
  image_url: string | null
  created_at: string
}

interface CatalogAnswer {
  answer: string
}

/** Mirrors backend schemas.QuestionText (stripped, 1 to 500 characters). */
export const QUESTION_MAX_LENGTH = 500

export type CallOptions = Pick<RequestOptions, 'signal' | 'onSlow'>

export function fetchProducts(options: CallOptions = {}): Promise<Product[]> {
  return requestJson<Product[]>('/api/v1/products', options)
}

export async function askCatalog(question: string, options: CallOptions = {}): Promise<string> {
  const { answer } = await requestJson<CatalogAnswer>('/api/v1/catalog/ask', {
    ...options,
    method: 'POST',
    body: { question },
  })
  return answer
}
