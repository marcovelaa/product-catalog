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
