import { useEffect, useRef, type FormEvent, type KeyboardEvent, type Ref } from 'react'
import type { ChatMessage } from '../hooks/useCatalogChat'

interface ChatPanelProps {
  messages: ChatMessage[]
  starters: string[]
  draft: string
  maxLength: number
  isSending: boolean
  latestAnswer: string
  inputRef?: Ref<HTMLTextAreaElement>
  onDraftChange: (value: string) => void
  onSubmit: () => void
  onStarter: (question: string) => void
  onRetry: (messageId: string) => void
}

export function ChatPanel({
  messages,
  starters,
  draft,
  maxLength,
  isSending,
  latestAnswer,
  inputRef,
  onDraftChange,
  onSubmit,
  onStarter,
  onRetry,
}: ChatPanelProps) {
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [messages])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSubmit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      onSubmit()
    }
  }

  const canSend = !isSending && draft.trim().length > 0

  return (
    <section id="ask" className="chat" aria-labelledby="chat-title">
      <div className="chat__head">
        <h2 id="chat-title" className="section-title rise" style={{ '--d': '200ms' } as React.CSSProperties}>
          Ask the catalog
        </h2>
        <p className="chat__intro rise" style={{ '--d': '280ms' } as React.CSSProperties}>
          Answers come only from the live product list, in the language you write in.
        </p>
      </div>

      <div ref={logRef} className="chat__log">
        {messages.length === 0 ? (
          <ul className="starters" aria-label="Suggested questions">
            {starters.map((question, index) => (
              <li key={question} className="rise" style={{ '--d': `${360 + index * 80}ms` } as React.CSSProperties}>
                <button type="button" className="starter" onClick={() => onStarter(question)} disabled={isSending}>
                  {question}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <ul className="messages">
            {messages.map((message) => (
              <MessageItem key={message.id} message={message} isSending={isSending} onRetry={onRetry} />
            ))}
          </ul>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {latestAnswer}
      </p>

      <form className="chat__form" onSubmit={handleSubmit}>
        <label htmlFor="question" className="chat__label">
          Your question
        </label>
        <div className="chat__bar">
          <textarea
            id="question"
            ref={inputRef}
            className="chat__input"
            rows={2}
            maxLength={maxLength}
            value={draft}
            disabled={isSending}
            placeholder="For example, what costs less than 40?"
            aria-describedby="question-hint"
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button type="submit" className="btn btn--ink" disabled={!canSend}>
            {isSending ? 'Sending' : 'Send'}
          </button>
        </div>
        <p id="question-hint" className="chat__hint">
          <span>Enter sends, Shift and Enter starts a new line.</span>
          <span className="chat__count">
            {draft.length} / {maxLength}
          </span>
        </p>
      </form>
    </section>
  )
}

interface MessageItemProps {
  message: ChatMessage
  isSending: boolean
  onRetry: (messageId: string) => void
}

function MessageItem({ message, isSending, onRetry }: MessageItemProps) {
  if (message.role === 'user') {
    return (
      <li className="message message--user">
        <span className="sr-only">You asked: </span>
        {message.text}
      </li>
    )
  }

  if (message.status === 'pending') {
    return (
      <li className="message message--assistant" aria-busy="true">
        <span className="pending">
          <span className="pending__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {message.slow
            ? 'Waking up the server. This can take up to a minute.'
            : 'Looking through the catalog.'}
        </span>
      </li>
    )
  }

  if (message.status === 'error') {
    return (
      <li className="message message--assistant message--error">
        <p>{message.error}</p>
        <button type="button" className="btn btn--paper" onClick={() => onRetry(message.id)} disabled={isSending}>
          Try again
        </button>
      </li>
    )
  }

  // Rendered as a text node: React escapes it, so an answer can never inject markup.
  return (
    <li className="message message--assistant">
      <span className="sr-only">Assistant: </span>
      {message.text}
    </li>
  )
}
