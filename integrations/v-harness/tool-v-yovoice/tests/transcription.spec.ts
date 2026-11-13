import { afterEach, describe, expect, it, vi } from 'vitest'
import { fullTranscript, fullUploadLimit, modelRows, resolveConfig, transcriptText, uploadLimit, voiceJson } from '../src/features/transcription/client.ts'

afterEach(() => vi.unstubAllGlobals())

describe('V-yovoice configuration and wire parsing', () => {
  it('requires an explicit model and clean service root', () => {
    expect(() => resolveConfig({})).toThrow()
    expect(() => resolveConfig({ baseUrl: 'http://localhost', model: '' })).toThrow()
    expect(() => resolveConfig({ baseUrl: 'http://user:secret@localhost', model: 'asr' })).toThrow()
    expect(() => resolveConfig({ baseUrl: 'http://localhost', model: 'asr', maxUploadBytes: -1 })).toThrow()
    expect(resolveConfig({ baseUrl: 'http://localhost/', model: 'asr' }).baseUrl).toBe('http://localhost')
  })
  it('distinguishes installed models from inference-ready models', () => {
    expect(modelRows([{ kind: 'asr', key: 'a', name: 'A', status: 'ready', inference_ready: false },
      { kind: 'asr', key: 'b', name: 'B', status: 'ready', inference_ready: true }, { kind: 'tts' }])).toEqual([
      { key: 'a', name: 'A', ready: false }, { key: 'b', name: 'B', ready: true },
    ])
    expect(() => modelRows({})).toThrow()
    expect(() => modelRows([{ kind: 'asr' }])).toThrow()
  })
  it('enforces the smallest byte limit and preserves exact text', () => {
    expect(uploadLimit({ max_upload_bytes: 100, limits: { input_bytes: 80 } }, 90)).toBe(80)
    expect(() => uploadLimit({ limits: {} }, 90)).toThrow()
    expect(transcriptText({ text: ' 原文\n' })).toBe(' 原文\n')
    expect(transcriptText({ text: '' })).toBe('')
    expect(() => transcriptText({})).toThrow()
  })
  it('requires complete full-file results matching the original audio and model', () => {
    const limits = { max_upload_bytes: 2000, limits: { input_bytes: 20 }, full_transcription: {
      endpoint: '/v1/audio/transcriptions/full', max_upload_bytes: 1000, processing_version: 'full-file-v1',
    } }
    expect(fullUploadLimit(limits, 1500)).toBe(1000)
    expect(fullUploadLimit({ limits: {} }, 1500)).toBeUndefined()
    expect(() => fullUploadLimit({ ...limits, limits: null }, 1500)).toThrow()
    const result = { complete: true, text: '全文', model: 'asr', cache: { source_sha256: 'source', key: 'a'.repeat(64) } }
    expect(fullTranscript(result, 'source', 'asr')).toEqual({ text: '全文', cacheKey: 'a'.repeat(64) })
    expect(() => fullTranscript({ ...result, complete: false }, 'source', 'asr')).toThrow()
    expect(() => fullTranscript(result, 'other', 'asr')).toThrow()
    expect(() => fullTranscript(result, 'source', 'other')).toThrow()
  })
  it('cancels an HTTP request before dispatch', async () => {
    const signal = AbortSignal.abort()
    await expect(voiceJson(resolveConfig({ baseUrl: 'http://127.0.0.1:1', model: 'asr' }), '/', signal)).rejects.toThrow()
  })
})


it('rejects upstream errors and oversized responses without partial success', async () => {
  const config = resolveConfig({ baseUrl: 'http://localhost', model: 'asr', maxResponseBytes: 1024 })
  vi.stubGlobal('fetch', async () => new Response('unavailable', { status: 503 }))
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('HTTP 503')
  vi.stubGlobal('fetch', async () => new Response('busy', { status: 429 }))
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('compute scheduler refused admission')
  vi.stubGlobal('fetch', async () => new Response('large', { status: 413 }))
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('HTTP 413')
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'audio duration exceeds maximum', error: { code: 'audio_duration_too_large' }, partial: { text: 'must not be saved' } }), { status: 413 }))
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('audio_duration_too_large')
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'audio exceeds calibrated duration' }), { status: 422 }))
  await expect(voiceJson({ ...config, maxResponseBytes: 1024 }, '/', new AbortController().signal)).rejects.toThrow('audio exceeds calibrated duration')
  vi.stubGlobal('fetch', async () => new Response('{"text":"long"}'))
  await expect(voiceJson({ ...config, maxResponseBytes: 3 }, '/', new AbortController().signal)).rejects.toThrow('maxResponseBytes')
  vi.stubGlobal('fetch', async () => { throw new TypeError('network unavailable') })
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('unreachable')
})

it('keeps the deadline active while reading a stalled response body', async () => {
  const config = resolveConfig({ baseUrl: 'http://localhost', model: 'asr', requestTimeoutMs: 20 })
  vi.stubGlobal('fetch', async () => new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('{"text":')) } })))
  await expect(voiceJson(config, '/', new AbortController().signal)).rejects.toThrow('No audio was submitted by this request')
  await expect(voiceJson(config, '/', new AbortController().signal, new FormData())).rejects.toThrow('outcome is unknown')
})

it('queries a service catalogue before a model has been selected', () => {
  expect(resolveConfig({ baseUrl: 'http://localhost' }, false).model).toBe('')
})
