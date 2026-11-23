// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import type { DictationControlProps } from '../src/client/dictation.tsx'
import { DictationControl } from '../src/client/dictation.tsx'
import { Recording, RecordingError } from '../src/client/recording.ts'
import { zh } from '../src/client/locales.ts'

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function translate(key: keyof typeof zh, values: Record<string, string | number> = {}): string {
  let text: string = zh[key]
  for (const [name, value] of Object.entries(values)) text = text.replace(`{${name}}`, String(value))
  return text
}

function fixture(options: {
  insert?: boolean
  text?: string
  error?: Error
  captureError?: Error
  maxSeconds?: number
} = {}) {
  const capture = new Recording(() => {})
  capture.start = vi.fn(async () => {})
  const stop = vi.fn(async () => new Uint8Array(48))
  capture.stop = stop
  capture.amplitude = () => 0
  const dispose = vi.fn(async () => {})
  capture.dispose = dispose
  const captureInsertion = vi.fn(() => ({ start: 3, end: 3, draftRev: 1 }))
  const insertText = vi.fn(() => options.insert ?? true)
  const submit = vi.fn()
  const inputActions: DictationControlProps['inputActions'] = {
    insertQuote: () => false,
    captureInsertion,
    insertText,
    setDraft: vi.fn(),
    insertRegionTokens: () => false,
    persistDraft: vi.fn(),
    addAttachments: () => true,
    removeAttachment: vi.fn(),
    pruneAttachments: vi.fn(),
    submit,
  }
  const transcribe = vi.fn(async () => {
    if (options.error !== undefined) throw options.error
    return { text: options.text ?? '检查 TypeScript 类型', model: 'sensevoice' }
  })
  const loadLimits = vi.fn(async () => ({ maxSeconds: options.maxSeconds ?? 120, maxAudioBytes: 10_000 }))
  if (options.captureError !== undefined) capture.start = vi.fn(async () => { throw options.captureError })
  const props: DictationControlProps = {
    sessionId: 'one' as SessionId,
    inputActions,
    locked: false,
    onActiveChange: vi.fn(),
    loadLimits,
    createRecording: () => capture,
    transcribe,
    t: translate as DictationControlProps['t'],
  }
  const view = render(<DictationControl {...props} />)
  return { props, view, capture, inputActions, stop, dispose, insertText, submit, transcribe, loadLimits }
}

async function start(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: zh.start }))
  await screen.findByRole('button', { name: zh.stop })
}

it('records, transcribes and inserts reviewable text without submitting the draft', async () => {
  const built = fixture()
  await start()
  expect(built.props.onActiveChange).toHaveBeenLastCalledWith(true)
  expect(screen.getByRole('img', { name: zh.recording })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: zh.stop }))
  await waitFor(() => {
    expect(built.insertText).toHaveBeenCalledWith('检查 TypeScript 类型', { start: 3, end: 3, draftRev: 1 })
  })
  expect(built.submit).not.toHaveBeenCalled()
  expect(built.props.onActiveChange).toHaveBeenLastCalledWith(false)
  expect(screen.queryByRole('button', { name: zh.stop })).toBeNull()
})

it.each(['cancel', 'escape', 'blur', 'hidden'])('releases a recording without recognizing on %s', async (action) => {
  const built = fixture()
  await start()
  if (action === 'cancel') fireEvent.click(screen.getByRole('button', { name: zh.cancel }))
  if (action === 'escape') fireEvent.keyDown(document, { key: 'Escape' })
  if (action === 'blur') fireEvent.blur(window)
  if (action === 'hidden') {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    try { fireEvent(document, new Event('visibilitychange')) } finally {
      delete (document as { hidden?: boolean }).hidden
    }
  }
  await screen.findByRole('button', { name: zh.start })
  expect(built.dispose).toHaveBeenCalled()
  expect(built.transcribe).not.toHaveBeenCalled()
})

it('keeps a transcript when the draft changed and retries insertion at the current cursor', async () => {
  const built = fixture({ insert: false })
  await start()
  fireEvent.click(screen.getByRole('button', { name: zh.stop }))
  const insert = await screen.findByRole('button', { name: zh.insert })
  expect((await screen.findByRole('status')).textContent).toContain('草稿已修改')
  built.insertText.mockReturnValueOnce(true)
  fireEvent.click(insert)
  await screen.findByRole('button', { name: zh.start })
  expect(built.insertText).toHaveBeenLastCalledWith('检查 TypeScript 类型', { start: 3, end: 3, draftRev: 1 })
})

it('bounds recording time and shows empty, service and capture failures locally', async () => {
  const bounded = fixture({ maxSeconds: 0.01 })
  await start()
  await waitFor(() => { expect(bounded.stop).toHaveBeenCalledWith(0.01) })
  await waitFor(() => { expect(bounded.insertText).toHaveBeenCalledOnce() })
  cleanup()

  fixture({ text: '' })
  await start()
  fireEvent.click(screen.getByRole('button', { name: zh.stop }))
  expect((await screen.findByRole('status')).textContent).toBe(zh.empty)
  cleanup()

  fixture({ error: new Error('offline') })
  await start()
  fireEvent.click(screen.getByRole('button', { name: zh.stop }))
  expect((await screen.findByRole('status')).textContent).toContain('offline')
  cleanup()

  fixture({ captureError: new RecordingError('permission') })
  fireEvent.click(screen.getByRole('button', { name: zh.start }))
  expect((await screen.findByRole('status')).textContent).toBe(zh.dictationPermission)
})

it('invalidates late results after a Session switch and honors the locked composer', async () => {
  const built = fixture()
  const waiting = Promise.withResolvers<{ text: string; model: string }>()
  built.transcribe.mockReturnValueOnce(waiting.promise)
  await start()
  fireEvent.click(screen.getByRole('button', { name: zh.stop }))
  built.view.rerender(<DictationControl {...built.props} sessionId={'two' as SessionId} />)
  await act(async () => { waiting.resolve({ text: 'late', model: 'sensevoice' }) })
  expect(built.insertText).not.toHaveBeenCalled()

  built.view.rerender(<DictationControl {...built.props} sessionId={'one' as SessionId} locked />)
  expect(screen.getByRole<HTMLButtonElement>('button', { name: zh.start }).disabled).toBe(true)
})
