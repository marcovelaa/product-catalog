import { ApiError } from './client'
import { QUESTION_MAX_LENGTH } from './catalog'

/** Turns any request failure into one calm, user-facing sentence. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Algo salió mal. Inténtalo de nuevo.'
  switch (error.kind) {
    case 'network':
      return 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'
    case 'timeout':
      return 'El servidor tardó demasiado en responder. Puede que aún esté despertando, así que inténtalo de nuevo.'
    case 'validation':
      return `Las preguntas deben tener entre 1 y ${QUESTION_MAX_LENGTH} caracteres.`
    case 'aborted':
      return 'La solicitud fue cancelada.'
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
      return 'El servidor no respondió, quizá porque está despertando. Inténtalo de nuevo en un momento. Si el producto ya aparece en la lista, se guardó.'
    case 'validation':
      return error.detail
        ? `El servidor no aceptó el producto (${error.detail}). Revisa los campos e inténtalo de nuevo.`
        : 'El servidor no aceptó el producto. Revisa los campos e inténtalo de nuevo.'
    case 'http':
      return `No se pudo guardar el producto${error.status ? ` (error ${error.status})` : ''}. Inténtalo de nuevo en un momento.`
    case 'aborted':
      return describeError(error)
  }
}

function describeStatus(status: number | undefined): string {
  switch (status) {
    case 429:
      return 'El asistente está ocupado en este momento. Inténtalo de nuevo en un minuto.'
    case 502:
      return 'El asistente no pudo responder en este momento. Inténtalo de nuevo en un minuto.'
    case 503:
      return 'El asistente aún no está configurado. Inténtalo más tarde.'
    default:
      return `El servidor respondió con un error${status ? ` (${status})` : ''}. Inténtalo de nuevo.`
  }
}
