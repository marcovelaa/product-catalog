import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatMessage } from '../hooks/useCatalogChat'
import { ChatPanel } from './ChatPanel'

const props = {
  messages: [] as ChatMessage[],
  starters: ['Which products are in stock right now?'],
  draft: '',
  maxLength: 500,
  isSending: false,
  latestAnswer: '',
  onDraftChange: () => {},
  onSubmit: () => {},
  onStarter: () => {},
  onRetry: () => {},
}

describe('ChatPanel', () => {
  it('renders answers as plain text, never as markup', () => {
    const answer = '<img src=x onerror=alert(1)><b>bold</b>'
    const messages: ChatMessage[] = [{ id: 'a', role: 'assistant', text: answer, status: 'done', slow: false }]
    const { container } = render(<ChatPanel {...props} messages={messages} latestAnswer={answer} />)

    expect(container.querySelector('img, b')).toBeNull()
    expect(screen.getAllByText(answer, { exact: false })).not.toHaveLength(0)
  })

  it('sends on Enter but not on Shift+Enter', () => {
    const onSubmit = vi.fn()
    render(<ChatPanel {...props} draft="Hi?" onSubmit={onSubmit} />)
    const input = screen.getByLabelText('Your question')

    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('caps the input at the backend limit and disables it while sending', () => {
    render(<ChatPanel {...props} isSending />)
    const input = screen.getByLabelText('Your question')

    expect(input).toHaveAttribute('maxlength', '500')
    expect(input).toBeDisabled()
  })

  it('announces new answers politely', () => {
    render(<ChatPanel {...props} latestAnswer="Three products are in stock." />)
    expect(screen.getByText('Three products are in stock.')).toHaveAttribute('aria-live', 'polite')
  })
})
