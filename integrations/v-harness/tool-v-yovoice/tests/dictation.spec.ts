import { afterEach, expect, it } from 'vitest'
import { createServer } from 'node:http'
import { once } from 'node:events'
import { resolveConfig } from '../src/core/config.ts'
import { dictationLimits, transcribeDictation } from '../src/features/dictation/index.ts'

const cleanup: (() => Promise<unknown>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

function wave(seconds = 0.1): Uint8Array<ArrayBuffer> {
  const samples = Math.floor(seconds * 16_000)
  const bytes = new Uint8Array(44 + samples * 2)
  const view = new DataView(bytes.buffer)
  const text = (at: number, value: string): void => {
    for (let index = 0; index < value.length; index++) bytes[at + index] = value.charCodeAt(index)
  }
  text(0, 'RIFF')
  view.setUint32(4, bytes.length - 8, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 16_000, true)
  view.setUint32(28, 32_000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, samples * 2, true)
  return bytes
}

function base64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64')
}

async function fixture(options: {
  ready?: boolean
  uploadLimit?: number
  text?: string
  status?: number
} = {}) {
  const requests: { path: string; body: string }[] = []
  const server = createServer((req, res) => {
    void (async () => {
      const chunks: Buffer[] = []
      for await (const chunk of req) chunks.push(Buffer.from(String(chunk)))
      const body = Buffer.concat(chunks).toString('utf8')
      requests.push({ path: req.url ?? '', body })
      res.setHeader('content-type', 'application/json')
      if (req.url === '/api/v1/models') {
        res.end(JSON.stringify([{
          kind: 'asr', key: 'sensevoice', name: 'SenseVoice',
          status: options.ready === false ? 'not_installed' : 'ready',
          inference_ready: options.ready !== false,
        }]))
        return
      }
      if (req.url?.endsWith('/input-limits')) {
        res.end(JSON.stringify({ max_upload_bytes: 10_000, limits: { input_bytes: options.uploadLimit ?? 10_000 } }))
        return
      }
      if (req.url === '/v1/audio/transcriptions') {
        if (options.status !== undefined) {
          res.statusCode = options.status
          res.end(JSON.stringify({ detail: 'scheduler busy' }))
          return
        }
        res.end(JSON.stringify({ text: options.text ?? '你好，V-yovoice' }))
        return
      }
      res.statusCode = 404
      res.end()
    })().catch((error: unknown) => {
      res.statusCode = 500
      res.end(String(error))
    })
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  cleanup.push(() => new Promise<void>((resolve, reject) => {
    server.closeAllConnections()
    server.close((error) => { if (error) reject(error); else resolve() })
  }))
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('missing server address')
  const config = resolveConfig({
    baseUrl: `http://127.0.0.1:${address.port}`,
    model: 'sensevoice',
    maxDictationSeconds: 120,
  })
  return { config, requests }
}

it('sends one bounded canonical WAV to the configured ASR model without creating a Session result', async () => {
  const built = await fixture()
  const recording = base64(wave())
  const result = await transcribeDictation(built.config, { audioBase64: recording }, new AbortController().signal)
  expect(result).toEqual({ text: '你好，V-yovoice', model: 'sensevoice' })
  expect(built.requests.map(request => request.path).sort()).toEqual([
    '/api/v1/models', '/api/v1/models/sensevoice/input-limits', '/v1/audio/transcriptions',
  ])
  expect(built.requests.at(-1)?.path).toBe('/v1/audio/transcriptions')
  const upload = built.requests.at(-1)?.body ?? ''
  expect(upload).toContain('name="model"')
  expect(upload).toContain('sensevoice')
  expect(upload).toContain('filename="dictation.wav"')
})

it('rejects malformed, noncanonical, oversized and cancelled recordings before upload', async () => {
  const built = await fixture()
  const signal = new AbortController().signal
  await expect(transcribeDictation(built.config, { audioBase64: 'not-a-wave' }, signal)).rejects.toThrow(/canonical|WAV/u)
  await expect(transcribeDictation(built.config, { audioBase64: base64(new Uint8Array(12)) }, signal)).rejects.toThrow(/WAV/u)
  await expect(transcribeDictation(built.config, { audioBase64: `${base64(wave())}====` }, signal)).rejects.toThrow(/canonical/u)
  await expect(transcribeDictation(built.config, {
    audioBase64: base64(wave(built.config.maxDictationSeconds + 1)),
  }, signal)).rejects.toThrow(/byte limit/u)
  await expect(transcribeDictation(built.config, { audioBase64: base64(wave()) }, AbortSignal.abort())).rejects.toThrow()
  expect(built.requests).toHaveLength(0)
})

it('reports model readiness, calibrated limits and service admission failures', async () => {
  const unavailable = await fixture({ ready: false })
  await expect(transcribeDictation(unavailable.config, {
    audioBase64: base64(wave()),
  }, new AbortController().signal)).rejects.toThrow(/not inference-ready/u)

  const limited = await fixture({ uploadLimit: 1000 })
  await expect(transcribeDictation(limited.config, {
    audioBase64: base64(wave()),
  }, new AbortController().signal)).rejects.toThrow(/upload limit/u)

  const busy = await fixture({ status: 429 })
  await expect(transcribeDictation(busy.config, {
    audioBase64: base64(wave()),
  }, new AbortController().signal)).rejects.toThrow(/busy/u)
})

it('derives the shared recording bound from the WAV duration and deployment cap', () => {
  const builtConfig = resolveConfig({
    baseUrl: 'http://voice:7070',
    model: 'sensevoice',
    maxDictationSeconds: 90,
  })
  expect(dictationLimits(builtConfig)).toEqual({ maxSeconds: 90, maxAudioBytes: 44 + 90 * 32_000 })
  expect(dictationLimits({ ...builtConfig, maxUploadBytes: 100_000 })).toEqual({ maxSeconds: 90, maxAudioBytes: 100_000 })
})
