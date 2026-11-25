/** Mirrors backend schemas.ProductBase (name 1 to 200 stripped, price >= 0, stock >= 0, image_url <= 2048). */
export const PRODUCT_NAME_MAX_LENGTH = 200
export const IMAGE_URL_MAX_LENGTH = 2048
/** The stock column is a 32-bit integer; the API schema has no upper bound of its own. */
export const STOCK_MAX = 2_147_483_647

export interface ProductFormValues {
  name: string
  price: string
  stock: string
  imageUrl: string
}

export type ProductField = keyof ProductFormValues
export type FieldErrors = Partial<Record<ProductField, string>>

/** The request body of POST /api/v1/products. */
export interface ProductInput {
  name: string
  price: number
  stock: number
  image_url: string | null
}

export type ParsedProduct = { ok: true; input: ProductInput } | { ok: false; errors: FieldErrors }

export const EMPTY_PRODUCT_FORM: ProductFormValues = { name: '', price: '', stock: '0', imageUrl: '' }

/** Field order on screen, used to find the first invalid field. */
export const PRODUCT_FIELDS: readonly ProductField[] = ['name', 'price', 'stock', 'imageUrl']

type Parsed<T> = { value: T } | { error: string }

export function parseProductForm(values: ProductFormValues): ParsedProduct {
  const name = parseName(values.name)
  const price = parsePrice(values.price)
  const stock = parseStock(values.stock)
  const imageUrl = parseImageUrl(values.imageUrl)

  if ('value' in name && 'value' in price && 'value' in stock && 'value' in imageUrl) {
    return {
      ok: true,
      input: { name: name.value, price: price.value, stock: stock.value, image_url: imageUrl.value },
    }
  }

  const errors: FieldErrors = {}
  if ('error' in name) errors.name = name.error
  if ('error' in price) errors.price = price.error
  if ('error' in stock) errors.stock = stock.error
  if ('error' in imageUrl) errors.imageUrl = imageUrl.error
  return { ok: false, errors }
}

function parseName(raw: string): Parsed<string> {
  const name = raw.trim()
  if (!name) return { error: 'Enter a name.' }
  if (name.length > PRODUCT_NAME_MAX_LENGTH) return { error: `Use ${PRODUCT_NAME_MAX_LENGTH} characters or fewer.` }
  return { value: name }
}

function parsePrice(raw: string): Parsed<number> {
  const text = raw.trim()
  if (!text) return { error: 'Enter a price.' }
  const price = Number(text)
  if (!Number.isFinite(price)) return { error: 'Enter a number, for example 25.50.' }
  if (price < 0) return { error: 'The price cannot be negative.' }
  return { value: price }
}

/** An empty field means the backend default of 0. */
function parseStock(raw: string): Parsed<number> {
  const text = raw.trim()
  if (!text) return { value: 0 }
  if (!/^\d+$/.test(text)) return { error: 'Use a whole number, 0 or more.' }
  const stock = Number(text)
  if (stock > STOCK_MAX) return { error: `Use a number up to ${STOCK_MAX.toLocaleString('en-US')}.` }
  return { value: stock }
}

/** Empty means no image (null). Only http and https links are accepted. */
function parseImageUrl(raw: string): Parsed<string | null> {
  const text = raw.trim()
  if (!text) return { value: null }
  if (text.length > IMAGE_URL_MAX_LENGTH) return { error: `Use ${IMAGE_URL_MAX_LENGTH} characters or fewer.` }
  try {
    const { protocol } = new URL(text)
    if (protocol === 'http:' || protocol === 'https:') return { value: text }
  } catch {
    // Falls through to the shared message below.
  }
  return { error: 'Use a link that starts with http:// or https://.' }
}
