// The API stores prices as plain numbers; they are shown as bolivianos (Bs), with no conversion.
const priceFormat = new Intl.NumberFormat('es-BO', { style: 'currency', currency: 'BOB' })
const countFormat = new Intl.NumberFormat('es')

export function formatPrice(price: number): string {
  return priceFormat.format(price)
}

export function formatCount(count: number): string {
  return countFormat.format(count)
}
