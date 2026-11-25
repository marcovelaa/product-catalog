import { describe, expect, it } from 'vitest'
import { parseProductForm, type ProductFormValues } from './productInput'

const valid: ProductFormValues = { name: 'Wireless Mouse', price: '25.50', stock: '12', imageUrl: '' }

function errorsFor(patch: Partial<ProductFormValues>) {
  const result = parseProductForm({ ...valid, ...patch })
  if (result.ok) throw new Error('expected validation to fail')
  return result.errors
}

describe('parseProductForm', () => {
  it('trims the name and turns an empty image link into null', () => {
    expect(parseProductForm({ ...valid, name: '  Wireless Mouse  ' })).toEqual({
      ok: true,
      input: { name: 'Wireless Mouse', price: 25.5, stock: 12, image_url: null },
    })
  })

  it('treats an empty stock as 0, the backend default', () => {
    expect(parseProductForm({ ...valid, stock: '  ' })).toMatchObject({ ok: true, input: { stock: 0 } })
  })

  it('accepts http and https image links and trims them', () => {
    expect(parseProductForm({ ...valid, imageUrl: ' https://cdn.test/mouse.png ' })).toMatchObject({
      ok: true,
      input: { image_url: 'https://cdn.test/mouse.png' },
    })
    expect(parseProductForm({ ...valid, imageUrl: 'http://cdn.test/mouse.png' })).toMatchObject({ ok: true })
  })

  it('requires a name of 1 to 200 characters after trimming', () => {
    expect(errorsFor({ name: '   ' }).name).toBe('Escribe un nombre.')
    expect(errorsFor({ name: 'x'.repeat(201) }).name).toBe('Usa 200 caracteres o menos.')
    expect(parseProductForm({ ...valid, name: 'x'.repeat(200) }).ok).toBe(true)
  })

  it('rejects an empty, non-numeric, infinite or negative price but accepts 0', () => {
    expect(errorsFor({ price: '' }).price).toBe('Escribe un precio.')
    expect(errorsFor({ price: 'abc' }).price).toBe('Escribe un número, por ejemplo 25,50.')
    expect(errorsFor({ price: '1e999' }).price).toBe('Escribe un número, por ejemplo 25,50.')
    expect(errorsFor({ price: '-0.01' }).price).toBe('El precio no puede ser negativo.')
    expect(parseProductForm({ ...valid, price: '0' })).toMatchObject({ ok: true, input: { price: 0 } })
  })

  it('rejects hex, binary, octal and exponent prices that Number() would silently coerce', () => {
    for (const price of ['0x1A', '0b11', '0o7', '1e3', '2E2', '1_000', '1,000.50', '1.000,50', '25,5,0', '+5', 'Infinity']) {
      expect(errorsFor({ price }).price, price).toBe('Escribe un número, por ejemplo 25,50.')
    }
  })

  it('accepts plain decimal prices, with or without a leading or trailing dot', () => {
    for (const [price, value] of [['25', 25], ['25.50', 25.5], ['.5', 0.5], ['25.', 25], ['25,50', 25.5], [',5', 0.5], ['0,99', 0.99]] as const) {
      expect(parseProductForm({ ...valid, price }), price).toMatchObject({ ok: true, input: { price: value } })
    }
  })

  it('rejects a stock that is not a whole number of 0 or more', () => {
    const message = 'Usa un número entero, 0 o más.'
    expect(errorsFor({ stock: '1.5' }).stock).toBe(message)
    expect(errorsFor({ stock: '-1' }).stock).toBe(message)
    expect(errorsFor({ stock: 'ten' }).stock).toBe(message)
    expect(errorsFor({ stock: '2147483648' }).stock).toBe('Usa un número de hasta 2.147.483.647.')
  })

  it('rejects image links that are not http or https, or longer than 2048 characters', () => {
    const message = 'Usa un enlace que empiece con http:// o https://.'
    expect(errorsFor({ imageUrl: 'javascript:alert(1)' }).imageUrl).toBe(message)
    expect(errorsFor({ imageUrl: 'ftp://files.test/a.png' }).imageUrl).toBe(message)
    expect(errorsFor({ imageUrl: 'not a link' }).imageUrl).toBe(message)
    expect(errorsFor({ imageUrl: `https://cdn.test/${'a'.repeat(2048)}` }).imageUrl).toBe(
      'Usa 2048 caracteres o menos.',
    )
  })

  it('reports every invalid field at once', () => {
    expect(Object.keys(errorsFor({ name: '', price: '', stock: 'x', imageUrl: 'nope' }))).toEqual([
      'name',
      'price',
      'stock',
      'imageUrl',
    ])
  })
})
