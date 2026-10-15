import { afterEach, describe, expect, it, vi } from 'vitest'
import { listenForVosBridgeLocale } from './vosBridge'

const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')

afterEach(() => {
  vi.useRealTimers()
  if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
  else Reflect.deleteProperty(globalThis, 'window')
})

describe('VOS locale bridge', () => {
  it('uses the same-origin creator bridge for embedded API docs', async () => {
    let handler: (state: { locale?: unknown }) => void = () => undefined
    Object.defineProperty(globalThis, 'window', { configurable: true, value: { parent: {
      vos_platform: {
        getState: async () => ({ locale: 'zh-Hant' }),
        broadcast: { on: (_event: string, listener: typeof handler) => { handler = listener; return () => undefined } },
      },
    } } })
    const applied: string[] = []
    const stop = listenForVosBridgeLocale(locale => applied.push(locale))
    await Promise.resolve()
    expect(applied).toEqual(['zh-TW'])
    handler({ locale: 'en-US' })
    expect(applied).toEqual(['zh-TW', 'en-US'])
    stop()
  })
  it('waits for late injection, reads the snapshot and unsubscribes', async () => {
    vi.useFakeTimers()
    const host: Partial<Window> = { parent: {} as Window }
    Object.defineProperty(globalThis, 'window', { configurable: true, value: host })
    const applied: string[] = []
    let handler: (state: { locale?: unknown }) => void = () => undefined
    let unsubscribed = false
    const stop = listenForVosBridgeLocale(locale => applied.push(locale))
    host.vos_platform = {
      broadcast: { on: (_event, listener) => { handler = listener; return () => { unsubscribed = true } } },
      getState: async () => ({ locale: 'en-US' }),
    }
    await vi.advanceTimersByTimeAsync(100)
    expect(applied).toEqual(['en-US'])
    handler({ locale: 'zh-HK' })
    expect(applied).toEqual(['en-US', 'zh-TW'])
    stop()
    expect(unsubscribed).toBe(true)
  })

  it('does not let a late snapshot overwrite a newer broadcast', async () => {
    let handler: (state: { locale?: unknown }) => void = () => undefined
    let resolveSnapshot: (state: { locale?: unknown }) => void = () => undefined
    const snapshot = new Promise<{ locale?: unknown }>(resolve => { resolveSnapshot = resolve })
    Object.defineProperty(globalThis, 'window', { configurable: true, value: {
      vos_platform: {
        broadcast: { on: (_event: string, listener: typeof handler) => { handler = listener; return () => undefined } },
        getState: () => snapshot,
      },
    } })
    const applied: string[] = []
    const stop = listenForVosBridgeLocale(locale => applied.push(locale))
    handler({ locale: 'zh-TW' })
    resolveSnapshot({ locale: 'en-US' })
    await Promise.resolve()
    expect(applied).toEqual(['zh-TW'])
    stop()
  })
})
