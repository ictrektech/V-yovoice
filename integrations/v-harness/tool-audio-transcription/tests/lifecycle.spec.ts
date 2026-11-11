import { afterEach, expect, it, vi } from 'vitest'
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
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage, ToolCallId } from '@deepseek-ai/dsh-llm'
import * as plugin from '../src/index.ts'

const cleanup: (() => Promise<unknown>)[] = []
afterEach(async () => { vi.unstubAllGlobals(); for (const dispose of cleanup.splice(0).reverse()) await dispose() })

async function fixture(config: Record<string, unknown> = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'audio-lifecycle-'))
  cleanup.push(() => rm(dir, { recursive: true, force: true }))
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
  await ctx.loader.create({ name: 'cordis:audio', config })
  await ctx.loader.await()
  const ref = await ctx.attachments.saveFile({ name: 'sample.mp3', data: new Uint8Array([73, 68, 51]) })
  const session = ctx.sessions.create(SessionId('lifecycle'))
  session.append('user/message', createUserMessage({ source: { kind: 'user' }, content: [{ type: 'file', attachment: ref }] }), { surfaceOp: 'append' })
  return { ctx, agent: { session } as Agent }
}

it('loads without a service and reports configuration only when invoked', async () => {
  const { ctx, agent } = await fixture()
  expect(ctx.tools.get('transcribe_audio')).toBeDefined()
  const result = await executeModelToolFixture(ctx, { name: 'transcribe_audio', arguments: {}, agent, callId: ToolCallId('unconfigured'), signal: new AbortController().signal })
  expect(result.isError).toBe(true)
  expect(JSON.stringify(result.content)).toContain('Configure the V-yovoice service address')
})

it('aborts pending service requests and withdraws tools on unload', async () => {
  const { ctx, agent } = await fixture({ baseUrl: 'http://voice', model: 'sensevoice' })
  const started = Promise.withResolvers<AbortSignal>()
  vi.stubGlobal('fetch', (_input: RequestInfo | URL, init?: RequestInit) => {
    const signal = init?.signal
    if (!signal) throw new Error('Missing request lifetime')
    started.resolve(signal)
    return new Promise<Response>((_resolve, reject) => { signal.addEventListener('abort', () => { reject(signal.reason instanceof Error ? signal.reason : new Error('aborted')) }, { once: true }) })
  })
  const tools = ctx.tools
  const result = executeModelToolFixture(ctx, { name: 'transcribe_audio', arguments: {}, agent, callId: ToolCallId('unload'), signal: new AbortController().signal })
  const signal = await started.promise
  await ctx.fiber.dispose()
  expect(signal.aborted).toBe(true)
  expect((await result).isError).toBe(true)
  expect(tools.get('transcribe_audio')).toBeUndefined()
})

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    /** Test-only injected context, distinct from a human submission. */
    'audio-test-context': { kind: 'audio-test-context' }
  }
}

it('does not authorize file paths supplied by injected context', async () => {
  const { ctx, agent } = await fixture({ baseUrl: 'http://voice', model: 'sensevoice' })
  agent.session.append('user/message', createUserMessage({ source: { kind: 'audio-test-context' }, content: [{ type: 'text', text: '/etc/passwd' }] }), { surfaceOp: 'append' })
  const result = await executeModelToolFixture(ctx, { name: 'transcribe_audio', arguments: { file_path: '/etc/passwd' }, agent, callId: ToolCallId('injected'), signal: new AbortController().signal })
  expect(result.isError).toBe(true)
  expect(JSON.stringify(result.content)).toContain('File path must be explicitly supplied')
})
