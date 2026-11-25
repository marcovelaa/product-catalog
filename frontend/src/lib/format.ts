// The API stores prices as plain numbers with no currency; US dollars are assumed.
const priceFormat = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export function formatPrice(price: number): string {
  return priceFormat.format(price)
}
