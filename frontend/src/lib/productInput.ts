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
  if (!name) return { error: 'Escribe un nombre.' }
  if (name.length > PRODUCT_NAME_MAX_LENGTH) return { error: `Usa ${PRODUCT_NAME_MAX_LENGTH} caracteres o menos.` }
  return { value: name }
}

function parsePrice(raw: string): Parsed<number> {
  const text = raw.trim()
  if (!text) return { error: 'Escribe un precio.' }
  // Number() alone also accepts hex, binary, octal and exponent forms ("0x1A", "1e3"),
  // which would store a different value than the one typed.
  // The UI shows prices with a decimal comma, so a single "," or "." is accepted as the
  // decimal separator. Two separators ("1.000,50") are ambiguous and rejected.
  if (!/^-?(\d+[.,]?\d*|[.,]\d+)$/.test(text)) return { error: 'Escribe un número, por ejemplo 25,50.' }
  // "1.000" or "1,000" is how many Spanish speakers write one thousand, but would be read
  // as 1. Prices take at most 2 decimals, so that form is rejected instead of misread.
  if (/[.,]\d{3,}$/.test(text)) {
    return { error: 'Usa como máximo 2 decimales y sin separador de miles. Por ejemplo 1000 o 25,50.' }
  }
  const price = Number(text.replace(',', '.'))
  if (!Number.isFinite(price)) return { error: 'Escribe un número, por ejemplo 25,50.' }
  if (price < 0) return { error: 'El precio no puede ser negativo.' }
  return { value: price }
}

/** An empty field means the backend default of 0. */
function parseStock(raw: string): Parsed<number> {
  const text = raw.trim()
  if (!text) return { value: 0 }
  if (!/^\d+$/.test(text)) return { error: 'Usa un número entero, 0 o más.' }
  const stock = Number(text)
  if (stock > STOCK_MAX) return { error: `Usa un número de hasta ${STOCK_MAX.toLocaleString('es')}.` }
  return { value: stock }
}

/** Empty means no image (null). Only http and https links are accepted. */
function parseImageUrl(raw: string): Parsed<string | null> {
  const text = raw.trim()
  if (!text) return { value: null }
  if (text.length > IMAGE_URL_MAX_LENGTH) return { error: `Usa ${IMAGE_URL_MAX_LENGTH} caracteres o menos.` }
  try {
    const { protocol } = new URL(text)
    if (protocol === 'http:' || protocol === 'https:') return { value: text }
  } catch {
    // Falls through to the shared message below.
  }
  return { error: 'Usa un enlace que empiece con http:// o https://.' }
}
