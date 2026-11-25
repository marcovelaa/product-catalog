// The API stores prices as plain numbers with no currency, so none is shown.
const priceFormat = new Intl.NumberFormat('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const countFormat = new Intl.NumberFormat('es')

export function formatPrice(price: number): string {
  return priceFormat.format(price)
}

export function formatCount(count: number): string {
  return countFormat.format(count)
}
