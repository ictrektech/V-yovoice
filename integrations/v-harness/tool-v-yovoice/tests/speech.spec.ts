import { afterEach, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as NativeToolExecutor from '@deepseek-ai/dsh-tool-executor-native'
import { executeModelToolFixture } from '@deepseek-ai/dsh-tool-testkit'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import Projections from '@deepseek-ai/dsh-session-projection'
import Attachments from '@deepseek-ai/dsh-attachment-local'
import Fs from '@deepseek-ai/dsh-fs-local'
import { createServer } from 'node:http'
import { once } from 'node:events'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { createToolResultMessage, ToolCallId } from '@deepseek-ai/dsh-llm'
import * as plugin from '../src/index.ts'
import { audioPlaybackResponse } from '../src/core/playback.ts'

const cleanup: (() => Promise<unknown>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

const wav = Buffer.from('RIFF....WAVEfmt ')

async function fixture() {
  const dir = await mkdtemp(join(tmpdir(), 'speech-plugin-'))
  cleanup.push(() => rm(dir, { recursive: true, force: true }))
  const requests: { path: string; body: unknown }[] = []
  let ready = true
  let status = 200
  const server = createServer((req, res) => {
    void (async () => {
      const chunks: Buffer[] = []
      for await (const chunk of req) chunks.push(Buffer.from(String(chunk)))
      const raw = Buffer.concat(chunks).toString('utf8')
      const body = raw === '' ? null : JSON.parse(raw) as unknown
      requests.push({ path: req.url ?? '', body })
      if (req.url === '/api/v1/models') {
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify([
          { kind: 'asr', key: 'sensevoice', name: 'SenseVoice', status: 'ready', inference_ready: true },
          {
            kind: 'tts', key: 'kokoro', name: 'Kokoro', status: ready ? 'ready' : 'not_installed',
            languages: ['zh', 'en'], capabilities: ['builtin_voices'],
            voices: { zf_xiaoxiao: { language: 'zh' }, af_heart: { language: 'en' } },
          },
        ]))
        return
      }
      if (req.url === '/v1/audio/voices?model=kokoro') {
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify({
          object: 'list', model: 'kokoro', default_voice: 'zf_xiaoxiao',
          voices: [
            { id: 'zf_xiaoxiao', name: 'zf_xiaoxiao', language: 'zh' },
            { id: 'af_heart', name: 'af_heart', language: 'en' },
          ],
        }))
        return
      }
      if (req.url === '/v1/audio/speech') {
        if (status !== 200) {
          res.statusCode = status
          res.setHeader('content-type', 'application/json')
          res.end(JSON.stringify({ detail: status === 429 ? 'scheduler busy' : 'speech rejected' }))
          return
        }
        res.setHeader('content-type', 'audio/wav')
        res.end(wav)
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
  const ctx = new Context()
  cleanup.push(() => ctx.fiber.dispose())
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(NativeToolExecutor)
  await ctx.plugin(SessionStore)
  await ctx.plugin(Projections)
  await ctx.plugin(Attachments, { dshHome: dir })
  await ctx.plugin(Fs, { cwd: dir })
  ctx.provide('connection', { fetch: { register: () => async () => {} }, requestRejection: () => undefined })
  ctx.provide('webServer', { register: () => () => {} })
  await ctx.plugin(Loader)
  ctx.loader.builtins.audio = plugin
  await ctx.loader.create({
    name: 'cordis:audio',
    config: {
      baseUrl: `http://127.0.0.1:${address.port}`,
      model: 'sensevoice',
      speechModel: 'kokoro',
      speechVoice: 'zf_xiaoxiao',
      pageCharacters: 100,
    },
  })
  await ctx.loader.await()
  const session = ctx.sessions.create(SessionId('speech-owner'))
  const agent = { session } as Agent
  let serial = 0
  const call = (name: string, args: Record<string, unknown>, signal = new AbortController().signal, caller = agent) =>
    executeModelToolFixture(ctx, { name, arguments: args, callId: ToolCallId(`speech-${++serial}`), agent: caller, signal })
  return {
    ctx, session, call, requests,
    setReady: (value: boolean) => { ready = value },
    setStatus: (value: number) => { status = value },
  }
}

it('lists voices and generates a durable WAV through the public speech API', async () => {
  const built = await fixture()
  const { ctx, session, requests } = built
  const voices = await built.call('yovoice_voices', { language: 'zh' })
  expect(voices.isError).not.toBe(true)
  expect(JSON.stringify(voices.content)).toContain('zf_xiaoxiao')
  expect(JSON.stringify(voices.content)).not.toContain('af_heart')

  const args = { text: '你好，欢迎使用 V-Voice。', speed: 1.1, language: 'zh' }
  const result = await built.call('yovoice_speak', args)
  expect(result.isError).not.toBe(true)
  expect(result.meta).toMatchObject({
    audioSpeech: true, model: 'kokoro',
    voice: 'zf_xiaoxiao', text: args.text, bytes: wav.length,
  })
  const speechRequest = requests.find(request => request.path === '/v1/audio/speech')
  expect(speechRequest?.body).toMatchObject({
    model: 'kokoro', input: args.text, voice: 'zf_xiaoxiao', response_format: 'wav', speed: 1.1, language: 'zh',
  })
  const meta = result.meta
  if (typeof meta !== 'object' || meta === null || !('attachmentId' in meta) || typeof meta.attachmentId !== 'string'
    || !('file' in meta) || typeof meta.file !== 'string' || !('bytes' in meta) || typeof meta.bytes !== 'number') {
    throw new Error('speech metadata is incomplete')
  }
  expect(meta.file).toMatch(/^speech-.*\.wav$/u)
  const path = ctx.attachments.fileHostPath({ attachmentId: meta.attachmentId as never, name: meta.file, bytes: meta.bytes })
  expect(path).toBeDefined()
  expect(await readFile(path!)).toEqual(wav)

  session.append('tool/call', { turn: 1, step: 1, callId: ToolCallId('speech-result'), name: 'yovoice_speak', arguments: JSON.stringify(args) })
  session.append('tool/result', {
    turn: 1, step: 1,
    message: createToolResultMessage({ callId: ToolCallId('speech-result'), content: result.content, isError: false }),
    meta,
  }, { surfaceOp: 'append' })
  const projection = { stateOf: () => ({
    files: [], citations: [], transcripts: [], pendingCalls: [], pendingSpeechCalls: [],
    speeches: [meta],
  }) } as never
  const playback = await audioPlaybackResponse(ctx, new Request(
    `http://host/api/tool-audio-transcription/file?sessionId=speech-owner&attachmentId=${encodeURIComponent(meta.attachmentId)}`,
  ), projection)
  expect(playback.status).toBe(200)
  expect(playback.headers.get('content-type')).toBe('audio/wav')
  expect(Buffer.from(await playback.arrayBuffer())).toEqual(wav)
  const foreign = await audioPlaybackResponse(ctx, new Request(
    `http://host/api/tool-audio-transcription/file?sessionId=other&attachmentId=${encodeURIComponent(meta.attachmentId)}`,
  ), projection)
  expect(foreign.status).toBe(404)

  built.setReady(false)
  expect((await built.call('yovoice_speak', { text: 'model unavailable' })).isError).toBe(true)
  built.setReady(true)
  built.setStatus(429)
  const busy = await built.call('yovoice_speak', { text: 'busy' })
  expect(busy.isError).toBe(true)
  expect(JSON.stringify(busy.content)).toContain('busy')
  built.setStatus(200)
  expect((await built.call('yovoice_speak', { text: 'voice', voice: 'missing' })).isError).toBe(true)
  expect((await built.call('yovoice_speak', { text: 'emotion', emotion_text: 'calm' })).isError).toBe(true)
  const cancelled = await built.call('yovoice_speak', { text: 'cancel' }, AbortSignal.abort())
  expect(cancelled.isError).toBe(true)
})
