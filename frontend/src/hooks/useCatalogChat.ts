import { useCallback, useEffect, useRef, useState } from 'react'
import { askCatalog, QUESTION_MAX_LENGTH } from '../api/catalog'
import { ApiError } from '../api/client'
import { describeError } from '../api/messages'

export type MessageStatus = 'done' | 'pending' | 'error'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  status: MessageStatus
  /** Pending for longer than the slow threshold: the server is probably waking up. */
  slow: boolean
  error?: string
  /** On assistant messages, the question being answered (used by retry). */
  question?: string
}

export type AskFn = typeof askCatalog

export interface CatalogChat {
  messages: ChatMessage[]
  isSending: boolean
  latestAnswer: string
  /** Returns false when the question is blank, too long, or another is in flight. */
  send: (text: string) => boolean
  retry: (messageId: string) => void
}

export function useCatalogChat(ask: AskFn = askCatalog): CatalogChat {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [latestAnswer, setLatestAnswer] = useState('')
  const [isSending, setIsSending] = useState(false)
  const sendingRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)
  const nextId = useRef(0)

  useEffect(() => () => controllerRef.current?.abort(), [])

  const update = useCallback((id: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((m) => (m.id === id ? { ...m, ...patch } : m)))
  }, [])

  const request = useCallback(
    async (replyId: string, question: string) => {
      sendingRef.current = true
      setIsSending(true)
      const controller = new AbortController()
      controllerRef.current = controller
      try {
        const answer = await ask(question, {
          signal: controller.signal,
          onSlow: () => update(replyId, { slow: true }),
        })
        update(replyId, { status: 'done', text: answer, slow: false })
        setLatestAnswer(answer)
      } catch (error) {
        if (error instanceof ApiError && error.kind === 'aborted') return
        update(replyId, { status: 'error', error: describeError(error), slow: false })
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
        sendingRef.current = false
        setIsSending(false)
      }
    },
    [ask, update],
  )

  const send = useCallback(
    (text: string) => {
      const question = text.trim()
      if (sendingRef.current || !question || question.length > QUESTION_MAX_LENGTH) return false
      const userId = `m${nextId.current++}`
      const replyId = `m${nextId.current++}`
      setMessages((current) => [
        ...current,
        { id: userId, role: 'user', text: question, status: 'done', slow: false },
        { id: replyId, role: 'assistant', text: '', status: 'pending', slow: false, question },
      ])
      void request(replyId, question)
      return true
    },
    [request],
  )

  const retry = useCallback(
    (messageId: string) => {
      if (sendingRef.current) return
      const reply = messages.find((m) => m.id === messageId)
      if (!reply?.question || reply.status !== 'error') return
      update(messageId, { status: 'pending', error: undefined, slow: false })
      void request(messageId, reply.question)
    },
    [messages, request, update],
  )

  return { messages, isSending, latestAnswer, send, retry }
}
