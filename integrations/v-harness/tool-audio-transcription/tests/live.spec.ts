import { expect, it } from 'vitest'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import { Context } from '@deepseek-ai/cordis'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import Projections from '@deepseek-ai/dsh-session-projection'
import Attachments from '@deepseek-ai/dsh-attachment-local'
import Fs from '@deepseek-ai/dsh-fs-local'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage, ToolCallId } from '@deepseek-ai/dsh-llm'
import * as plugin from '../src/index.ts'

it.skipIf(!process.env.AUDIO_E2E_URL || !process.env.AUDIO_E2E_FILE)(
  'transcribes a known MP3 through the installed VOS service', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'audio-live-'))
    const ctx = new Context()
    try {
      await ctx.plugin(SystemPrompt)
      await ctx.plugin(Projections)
      await ctx.plugin(SessionStore)
      await ctx.plugin(ToolRuntime)
      await ctx.plugin(Attachments, { dshHome: dir })
      await ctx.plugin(Fs, { cwd: dir })
      const url = process.env.AUDIO_E2E_URL
      if (!url) throw new Error('AUDIO_E2E_URL is required')
      await ctx.plugin(Loader)
      ctx.loader.builtins.audio = plugin
      await ctx.loader.create({ name: 'cordis:audio', config: { baseUrl: url, model: process.env.AUDIO_E2E_MODEL ?? 'sensevoice-int8' } })
      await ctx.loader.await()
      const file = process.env.AUDIO_E2E_FILE
      if (!file) throw new Error('AUDIO_E2E_FILE is required')
      const ref = await ctx.attachments.saveFile({ name: 'known.mp3', data: await readFile(file) })
      const session = ctx.sessions.create(SessionId('live-audio'))
      session.append('user/message', createUserMessage({ source: { kind: 'user' }, content: [
        { type: 'text', text: 'What does this audio say?' }, { type: 'file', attachment: ref },
      ] }), { surfaceOp: 'append' })
      const result = await ctx.tools.execute({ name: 'transcribe_audio', arguments: { attachment_id: ref.attachmentId },
        callId: ToolCallId('live-audio'), agent: { session } as Agent, signal: new AbortController().signal })
      expect(result.isError, JSON.stringify(result.content)).not.toBe(true)
      const meta = result.meta
      if (typeof meta !== 'object' || meta === null || !('text' in meta) || typeof meta.text !== 'string') {
        throw new Error(JSON.stringify(result.content))
      }
      expect(meta.text.toLowerCase()).toContain('meeting starts at 9 tomorrow')
    } finally {
      await ctx.fiber.dispose()
      await rm(dir, { recursive: true, force: true })
    }
  }, 180_000,
)
