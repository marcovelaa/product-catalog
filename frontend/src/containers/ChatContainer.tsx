import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { QUESTION_MAX_LENGTH, type Product } from '../api/catalog'
import { ChatPanel } from '../components/ChatPanel'
import { useCatalogChat } from '../hooks/useCatalogChat'
import { buildStarterQuestions } from '../lib/starters'

interface ChatContainerProps {
  products: Product[]
  inputRef: RefObject<HTMLTextAreaElement | null>
}

export function ChatContainer({ products, inputRef }: ChatContainerProps) {
  const chat = useCatalogChat()
  const [draft, setDraft] = useState('')
  const starters = useMemo(() => buildStarterQuestions(products), [products])
  const wasSending = useRef(false)

  // The input is disabled while sending, which drops focus; give it back afterwards
  // unless the visitor has moved on to something else.
  useEffect(() => {
    if (wasSending.current && !chat.isSending && document.activeElement === document.body) {
      inputRef.current?.focus()
    }
    wasSending.current = chat.isSending
  }, [chat.isSending, inputRef])

  function submit() {
    if (chat.send(draft)) setDraft('')
  }

  return (
    <ChatPanel
      messages={chat.messages}
      starters={starters}
      draft={draft}
      maxLength={QUESTION_MAX_LENGTH}
      isSending={chat.isSending}
      latestAnswer={chat.latestAnswer}
      inputRef={inputRef}
      onDraftChange={setDraft}
      onSubmit={submit}
      onStarter={chat.send}
      onRetry={chat.retry}
    />
  )
}
