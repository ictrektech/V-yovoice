import { afterEach, expect, it } from 'vitest'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import LlmRuntime from '@deepseek-ai/dsh-llm'
import { provideWorkingDirectoryFixture } from '@deepseek-ai/dsh-agent-loop-testkit'
import { MockAdapter, textResponse, toolCallResponse } from '../../../core/agent-loop/tests/mock-adapter.ts'
import { Context } from '@deepseek-ai/cordis'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import Include from '@deepseek-ai/cordis-plugin-include'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createServer } from 'node:http'
import { once } from 'node:events'
import { createHash } from 'node:crypto'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as NativeToolExecutor from '@deepseek-ai/dsh-tool-executor-native'
import { executeModelToolFixture } from '@deepseek-ai/dsh-tool-testkit'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import Projections from '@deepseek-ai/dsh-session-projection'
import LocalAttachments from '@deepseek-ai/dsh-attachment-local'
import LocalFs from '@deepseek-ai/dsh-fs-local'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { createToolResultMessage, createUserMessage, ToolCallId } from '@deepseek-ai/dsh-llm'
import * as plugin from '../src/index.ts'
import { citesPath } from '../src/projection.ts'

const cleanup: (() => Promise<unknown>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

it('requires exact user path references rather than path prefixes', () => {
  expect(citesPath('read @"/tmp/a.mp3"', '/tmp/a.mp3')).toBe(true)
  expect(citesPath('请转写 /tmp/a.mp3，展示原文。', '/tmp/a.mp3')).toBe(true)
  expect(citesPath('请转写（/tmp/a.mp3）', '/tmp/a.mp3')).toBe(true)
  expect(citesPath('read /tmp/a.mp3.backup', '/tmp/a.mp3')).toBe(false)
  expect(citesPath('read /tmp/other.mp3', '/tmp/a.mp3')).toBe(false)
})

it('loads the real tools, uploads original bytes, persists full text, pages, resumes and refuses another session', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'audio-composition-'))
  cleanup.push(() => rm(dir, { recursive: true, force: true }))
  const requests: string[] = []
  let uploads = 0
  let ready = true
  let byteLimit = 10000
  let responseText = '第一段\n第二段\n第三段'
  let fullEnabled = false
  let fullComplete = true
  const server = createServer((req, res) => {
    void (async () => {
      const chunks: Buffer[] = []
      for await (const chunk of req) chunks.push(Buffer.from(String(chunk)))
      const body = Buffer.concat(chunks).toString('utf8')
      requests.push(req.url ?? '')
      res.setHeader('content-type', 'application/json')
      if (req.url === '/api/v1/models') res.end(JSON.stringify([{ kind: 'asr', key: 'sensevoice', name: 'SenseVoice', status: 'ready', inference_ready: ready }]))
      else if (req.url?.endsWith('/input-limits')) res.end(JSON.stringify({ max_upload_bytes: 10000, limits: { input_bytes: byteLimit },
        ...(fullEnabled ? { full_transcription: { endpoint: '/v1/audio/transcriptions/full', max_upload_bytes: 10000, processing_version: 'full-file-v1' } } : {}) }))
      else {
        expect(body).toContain('audio.mp3')
        expect(body).toContain('ID3-original-audio')
        uploads++
        res.end(JSON.stringify(fullEnabled ? { text: responseText, complete: fullComplete, model: 'sensevoice', cache: {
          source_sha256: createHash('sha256').update('ID3-original-audio').digest('hex'), key: 'a'.repeat(64),
        } } : { text: responseText }))
      }
    })().catch((error: unknown) => { res.statusCode = 500; res.end(String(error)) })
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  cleanup.push(() => new Promise<void>((resolve, reject) => {
    server.closeAllConnections()
    server.close((error) => { if (error) reject(error); else resolve() })
  }))
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('missing server address')
  const configPath = join(dir, 'cordis.yml')
  await writeFile(configPath, `- name: llm\n- name: agents\n- name: agent-loop\n- name: prompt\n- name: projections\n- name: sessions\n- name: tools\n- name: executor\n- name: attachments\n  config:\n    dshHome: ${JSON.stringify(dir)}\n- name: fs\n  config:\n    cwd: ${JSON.stringify(dir)}\n- name: audio\n  config:\n    baseUrl: http://127.0.0.1:${address.port}\n    model: sensevoice\n    pageCharacters: 4\n`)
  const ctx = new Context()
  cleanup.push(() => ctx.fiber.dispose())
  ctx.provide('connection', { fetch: { register: () => async () => {} }, requestRejection: () => undefined })
  ctx.provide('webServer', { register: () => () => {} })
  ctx.baseUrl = pathToFileURL(dir).href + '/'
  await ctx.plugin(Loader)
  ctx.loader.builtins.include = Include
  provideWorkingDirectoryFixture(ctx)
  const modules = new Map<string, unknown>([['llm', LlmRuntime], ['agents', AgentRegistry], ['agent-loop', AgentLoop], ['prompt', SystemPrompt], ['projections', Projections], ['sessions', SessionStore], ['tools', ToolRuntime], ['executor', NativeToolExecutor], ['attachments', LocalAttachments], ['fs', LocalFs], ['audio', plugin]])
  // Loader's importer uses only this operation in this fixture.
  Object.assign(ctx.loader, { internal: { version: 'v2', import: async (id: string) => modules.get(id) } })
  await ctx.loader.create({ name: 'cordis:include', config: { path: pathToFileURL(configPath).href } })
  await ctx.loader.await()
  expect(ctx.tools.get('transcribe_audio')).toBeDefined()
  const session = ctx.sessions.create(SessionId('audio-owner'))
  const agent = { session } as Agent
  const ref = await ctx.attachments.saveFile({ name: 'audio.mp3', data: Buffer.from('ID3-original-audio') })
  session.append('turn/start', { turn: 1 })
  session.append('user/message', createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: '这段音频内容是什么？' }, { type: 'file', attachment: ref }] }), { surfaceOp: 'append' })
  let serial = 0
  const call = (name: string, args: Record<string, unknown>, caller = agent) => executeModelToolFixture(ctx, { name, arguments: args, callId: ToolCallId(`audio-${++serial}`), agent: caller, signal: new AbortController().signal })
  expect(JSON.stringify((await call('list_audio_files', {})).content)).toContain('audio.mp3')
  const result = await call('transcribe_audio', { attachment_id: ref.attachmentId })
  expect(result.isError).not.toBe(true)
  expect(result.meta).toMatchObject({ text: '第一段\n第二段\n第三段', audioTranscript: true })
  expect(JSON.stringify(result.content)).toContain('next_offset')
  const meta = result.meta
  if (typeof meta !== 'object' || meta === null || !('source' in meta)) throw new Error('missing result source')
  const ptcSession = ctx.sessions.create(SessionId('audio-ptc'))
  ptcSession.append('tool/ptc-dispatch', {
    rootCallId: ToolCallId('root'), parentCallId: ToolCallId('root'), subCallId: ToolCallId('nested'),
    name: 'transcribe_audio', arguments: {}, isError: false, content: result.content, meta,
  })
  const restoredPtc = ctx.sessions.create(SessionId('audio-ptc-restored'), { seed: ptcSession.snapshotEvents() })
  const ptcResult = await call('read_audio_transcript', { source: meta.source }, { session: restoredPtc } as Agent)
  expect(JSON.stringify(ptcResult.content)).toContain('第一段')
  session.append('tool/call', { turn: 1, step: 1, callId: ToolCallId('unrelated-result'), name: 'unrelated_tool', arguments: '{}' })
  session.append('tool/result', { turn: 1, step: 1, message: createToolResultMessage({ callId: ToolCallId('unrelated-result'), content: result.content, isError: false }), meta }, { surfaceOp: 'append' })
  expect((await call('read_audio_transcript', { source: meta.source })).isError).toBe(true)
  session.append('tool/call', { turn: 1, step: 1, callId: ToolCallId('audio-result'), name: 'transcribe_audio', arguments: '{}' })
  session.append('tool/result', { turn: 1, step: 1, message: createToolResultMessage({ callId: ToolCallId('audio-result'), content: result.content, isError: false }), meta }, { surfaceOp: 'append' })
  const next = await call('read_audio_transcript', { source: meta.source, offset: 4 })
  expect(next.isError).not.toBe(true)
  expect(uploads).toBe(1)
  await call('transcribe_audio', { attachment_id: ref.attachmentId })
  expect(uploads).toBe(1)
  await call('transcribe_audio', { attachment_id: ref.attachmentId, reprocess: true })
  expect(uploads).toBe(2)
  const restored = { session: ctx.sessions.create(SessionId('restored'), { seed: session.snapshotEvents() }) } as Agent
  expect((await call('read_audio_transcript', { source: meta.source, offset: 4 }, restored)).content).toEqual(next.content)
  const desktop = join(dir, 'desktop.mp3')
  await writeFile(desktop, 'ID3-original-audio')
  session.append('user/message', createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: `转写 @"${desktop}"` }] }), { surfaceOp: 'append' })
  expect((await call('transcribe_audio', { file_path: desktop })).isError).not.toBe(true)
  expect(uploads).toBe(2)
  const other = { session: ctx.sessions.create(SessionId('other')) } as Agent
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId }, other)).isError).toBe(true)
  expect((await call('read_audio_transcript', { source: meta.source }, other)).isError).toBe(true)
  expect((await call('transcribe_audio', { file_path: '/etc/passwd' })).isError).toBe(true)
  expect(requests.filter(path => path === '/v1/audio/transcriptions')).toHaveLength(2)
  expect((await call('transcribe_audio', {})).isError).not.toBe(true)
  const prefix = String(ref.attachmentId).replace('sha256:', '').slice(0, 8)
  expect((await call('transcribe_audio', { attachment_id: prefix })).isError).not.toBe(true)
  expect((await call('transcribe_audio', { attachment_id: ref.name })).isError).not.toBe(true)
  const missing = await call('read_audio_transcript', { source: 'not-transcribed' })
  expect(JSON.stringify(missing.content)).toContain('First call transcribe_audio')
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId, file_path: desktop })).isError).toBe(true)
  expect((await call('read_audio_transcript', { source: meta.source, offset: -1 })).isError).toBe(true)
  ready = false
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId, reprocess: true })).isError).toBe(true)
  // Cached transcripts remain readable when the service model is unavailable.
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId })).isError).not.toBe(true)
  ready = true
  byteLimit = 2
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId, reprocess: true })).isError).toBe(true)
  expect(uploads).toBe(2)
  byteLimit = 10000
  responseText = ''
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId, reprocess: true })).meta).toMatchObject({ text: '' })
  const cancelled = await executeModelToolFixture(ctx, { name: 'transcribe_audio', arguments: { attachment_id: ref.attachmentId }, callId: ToolCallId('cancelled'), agent, signal: AbortSignal.abort() })
  expect(cancelled.isError).toBe(true)

  expect({ preview: result.content, fullText: 'text' in meta ? meta.text : null, page: next.content }).toMatchSnapshot()
  const prompt = await ctx.systemPrompt.assemble()
  expect(prompt.sections.find(section => section.name === 'tool:audio-transcription')?.text).toContain('Never use read_audio_transcript before a successful transcribe_audio')
  expect({ recovery: missing.content, audioTools: prompt.tools.filter(tool => tool.name.includes('audio')) }).toMatchSnapshot('audio workflow recovery')
  const adapter = new MockAdapter([
    (options) => {
      const request = JSON.stringify(options)
      expect(request).toContain('For questions about an attached audio file, call transcribe_audio')
      expect(request).toContain('Read that path with your file tools when its contents are needed')
      expect(request).toContain('For audio attachments, this instruction takes precedence over any generic file-handle instruction')
      expect(request).toContain('Use this as the first tool for every audio attachment')
      expect(request).toContain('Never call read before transcribe_audio')
      return toolCallResponse('recognize-1', 'transcribe_audio', {})
    },
    textResponse('音频原文：\n第一段\n第二段\n第三段'),
  ])
  ctx.llm.registerAdapter(['mock'], adapter)
  const { agent: realAgent } = await ctx.agents.create({ sessionId: SessionId('audio-agent'), agentOptions: { provider: 'mock', model: 'model' } })
  responseText = '第一段\n第二段\n第三段'
  realAgent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: '这段音频内容是什么？' }, { type: 'file', attachment: ref }] }))
  await realAgent.whenIdle()
  expect(adapter.requests).toHaveLength(2)
  const durable = realAgent.session.snapshotEvents().filter(event => event.type === 'tool/result' || event.type === 'assistant/message')
  expect(durable.map(event => event.type === 'tool/result' ? { type: event.type, content: event.data.message.content, meta: event.data.meta && typeof event.data.meta === 'object' && !Array.isArray(event.data.meta) ? { ...event.data.meta, endpoint: '<voice-service>' } : event.data.meta } : { type: event.type, content: event.data.message.content })).toMatchSnapshot('agent audio transcription')
  expect(JSON.stringify(adapter.requests[1])).toContain('next_offset')
  fullEnabled = true
  byteLimit = 2
  const full = await call('transcribe_audio', { attachment_id: ref.attachmentId })
  expect(full.isError).not.toBe(true)
  expect(full.meta).toMatchObject({ text: responseText, cacheKey: 'a'.repeat(64) })
  expect(requests.at(-1)).toBe('/v1/audio/transcriptions/full')
  fullComplete = false
  expect((await call('transcribe_audio', { attachment_id: ref.attachmentId })).isError).toBe(true)
  expect((await call('read_audio_transcript', { source: meta.source, offset: 4 })).content).toEqual(next.content)
  const tools = ctx.tools
  await ctx.fiber.dispose()
  expect(tools.get('transcribe_audio')).toBeUndefined()
})
