import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deferred, hangingFetch, jsonResponse, stubFetch } from '../test/fetchMock'
import { QUESTION_MAX_LENGTH } from '../api/catalog'
import { useCatalogChat } from './useCatalogChat'

describe('useCatalogChat', () => {
  let fetchMock: ReturnType<typeof stubFetch>

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = stubFetch()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('adds the user message optimistically with a pending reply and posts the trimmed question', () => {
    fetchMock.mockImplementation(hangingFetch())
    const { result } = renderHook(() => useCatalogChat())

    let accepted = false
    act(() => {
      accepted = result.current.send('  Is the mouse in stock?  ')
    })

    expect(accepted).toBe(true)
    expect(result.current.isSending).toBe(true)
    expect(result.current.messages).toMatchObject([
      { role: 'user', text: 'Is the mouse in stock?', status: 'done' },
      { role: 'assistant', text: '', status: 'pending', slow: false },
    ])
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/v1\/catalog\/ask$/)
    expect(init?.body).toBe('{"question":"Is the mouse in stock?"}')
  })

  it('replaces the pending reply with the answer and announces it', async () => {
    const response = deferred<Response>()
    fetchMock.mockReturnValue(response.promise)
    const { result } = renderHook(() => useCatalogChat())

    act(() => {
      result.current.send('Cheapest item?')
    })
    await act(async () => {
      response.resolve(jsonResponse({ answer: 'The Wireless Mouse, at 25.50.' }))
    })

    expect(result.current.isSending).toBe(false)
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      status: 'done',
      text: 'The Wireless Mouse, at 25.50.',
    })
    expect(result.current.latestAnswer).toBe('The Wireless Mouse, at 25.50.')
  })

  it('marks the pending reply as slow when the server has not answered after 3 seconds', async () => {
    fetchMock.mockImplementation(hangingFetch())
    const { result } = renderHook(() => useCatalogChat())

    act(() => {
      result.current.send('Anything in stock?')
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(result.current.messages[1]).toMatchObject({ status: 'pending', slow: true })
  })

  it('shows an error on the reply and recovers through retry', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: 'quota exceeded' }, 429))
      .mockResolvedValueOnce(jsonResponse({ answer: 'Three products are in stock.' }))
    const { result } = renderHook(() => useCatalogChat())

    await act(async () => {
      result.current.send('What is in stock?')
    })

    const reply = result.current.messages[1]
    expect(reply.status).toBe('error')
    expect(reply.error).toMatch(/busy/i)
    expect(result.current.isSending).toBe(false)

    await act(async () => {
      result.current.retry(reply.id)
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][1]?.body).toBe('{"question":"What is in stock?"}')
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1]).toMatchObject({
      status: 'done',
      text: 'Three products are in stock.',
    })
  })

  it('rejects blank and over-long questions without calling the server', () => {
    const { result } = renderHook(() => useCatalogChat())

    let blank = true
    let tooLong = true
    act(() => {
      blank = result.current.send('   ')
      tooLong = result.current.send('x'.repeat(QUESTION_MAX_LENGTH + 1))
    })

    expect(blank).toBe(false)
    expect(tooLong).toBe(false)
    expect(result.current.messages).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('ignores a new question while one is still being answered', () => {
    fetchMock.mockImplementation(hangingFetch())
    const { result } = renderHook(() => useCatalogChat())

    act(() => {
      result.current.send('First?')
    })
    let second = true
    act(() => {
      second = result.current.send('Second?')
    })

    expect(second).toBe(false)
    expect(result.current.messages).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aborts the request in flight when unmounted', () => {
    fetchMock.mockImplementation(hangingFetch())
    const { result, unmount } = renderHook(() => useCatalogChat())

    act(() => {
      result.current.send('Anything?')
    })
    unmount()

    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true)
  })
})
