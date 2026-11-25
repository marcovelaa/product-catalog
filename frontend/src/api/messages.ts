import { ApiError } from './client'
import { QUESTION_MAX_LENGTH } from './catalog'

/** Turns any request failure into one calm, user-facing sentence. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  switch (error.kind) {
    case 'network':
      return 'The server could not be reached. Check your connection and try again.'
    case 'timeout':
      return 'The server took too long to answer. It may still be waking up, so try again.'
    case 'validation':
      return `Questions need between 1 and ${QUESTION_MAX_LENGTH} characters.`
    case 'aborted':
      return 'The request was cancelled.'
    case 'http':
      return describeStatus(error.status)
  }
}

/** Like describeError, worded for saving a product. */
export function describeCreateError(error: unknown): string {
  if (!(error instanceof ApiError)) return describeError(error)
  switch (error.kind) {
    case 'network':
    case 'timeout':
      // The request may have reached the server before the connection dropped.
      return 'The server did not answer, perhaps because it is waking up. Try again in a moment. If the product already shows in the list, it was saved.'
    case 'validation':
      return error.detail
        ? `The server did not accept the product (${error.detail}). Check the fields and try again.`
        : 'The server did not accept the product. Check the fields and try again.'
    case 'http':
      return `The product could not be saved${error.status ? ` (error ${error.status})` : ''}. Please try again in a moment.`
    case 'aborted':
      return describeError(error)
  }
}

function describeStatus(status: number | undefined): string {
  switch (status) {
    case 429:
      return 'The assistant is busy right now. Please try again in a minute.'
    case 502:
      return 'The assistant could not answer right now. Please try again in a minute.'
    case 503:
      return 'The assistant is not set up yet. Please try again later.'
    default:
      return `The server answered with an error${status ? ` (${status})` : ''}. Please try again.`
  }
}
