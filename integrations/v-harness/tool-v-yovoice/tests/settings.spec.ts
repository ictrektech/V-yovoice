import { expect, it, onTestFinished } from 'vitest'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { boot, initProfile, readProfilePatches, type ProfileContext } from '@deepseek-ai/dsh-app-boot'
import ConfigEditor from '@deepseek-ai/dsh-config-editor'
import Settings from '@deepseek-ai/dsh-settings'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import Projections from '@deepseek-ai/dsh-session-projection'
import Attachments from '@deepseek-ai/dsh-attachment-local'
import Fs from '@deepseek-ai/dsh-fs-local'
import * as plugin from '../src/index.ts'

it('saves real profile settings, updates the running tool deadline, and restores after restart', async () => {
  const home = await mkdtemp(join(tmpdir(), 'audio-settings-'))
  onTestFinished(() => rm(home, { recursive: true, force: true }))
  const dir = join(home, 'profiles', 'test')
  initProfile(dir, ['audio-test'])
  const bundle = join(dir, 'node_modules', 'audio-test')
  await mkdir(bundle, { recursive: true })
  await writeFile(join(home, 'package.json'), '{"name":"test-installation"}')
  await writeFile(join(bundle, 'package.json'), JSON.stringify({ name: 'audio-test', version: '1.0.0', dsh: { bundle: { patch: 'cordis.patch.yml' } } }))
  await writeFile(join(bundle, 'cordis.patch.yml'), JSON.stringify([{ insert: [
    { id: 'config-editor', name: 'cordis:editor' }, { id: 'settings', name: 'cordis:settings' },
    { id: 'system-prompt', name: 'cordis:prompt' }, { id: 'tools', name: 'cordis:tools' },
    { id: 'projection', name: 'cordis:projections' }, { id: 'attachment', name: 'cordis:attachments', config: { dshHome: home } },
    { id: 'fs', name: 'cordis:fs', config: { cwd: home } }, { id: 'tool-audio-transcription', name: 'cordis:audio' },
  ] }]))
  const configPath = join(dir, 'cordis.yml')
  await writeFile(configPath, '[]')
  const profile: ProfileContext = { name: 'test', startedBundles: ['audio-test'], dir, patchPath: join(dir, 'cordis.patch.yml'), installAnchor: join(home, 'package.json'), cwd: home, home, overlays: [], telemetryDisabledEnv: undefined }
  const start = async () => {
    const ctx = await boot('test', configPath, readProfilePatches('test', profile), (ctx) => {
      ctx.provide('profileContext', profile)
      ctx.provide('appReady', { onReady: (listener: () => void) => { listener(); return () => {} } })
      ctx.provide('connection', { fetch: { register: () => async () => {} }, requestRejection: () => undefined })
      ctx.provide('webServer', { register: () => () => {} })
      Object.assign(ctx.loader.builtins, {
        editor: ConfigEditor, settings: Settings, prompt: SystemPrompt, tools: ToolRuntime,
        projections: Projections, attachments: Attachments, fs: Fs, audio: plugin,
      })
    })
    onTestFinished(() => ctx.fiber.dispose())
    return ctx
  }
  const ctx = await start()
  expect(ctx.tools.get('transcribe_audio')?.timeoutMs).toBe(1860000)
  await ctx.settings.update('tool-audio-transcription', { baseUrl: 'http://voice:7070', model: 'sensevoice-int8', requestTimeoutMs: 12345 })
  expect(ctx.tools.get('transcribe_audio')?.timeoutMs).toBe(12345)
  expect(await readFile(profile.patchPath, 'utf8')).toContain('http://voice:7070')
  await expect(ctx.settings.update('tool-audio-transcription', { baseUrl: 'http://user:secret@voice' })).rejects.toThrow()
  await ctx.fiber.dispose()
  const restored = await start()
  expect(restored.tools.get('transcribe_audio')?.timeoutMs).toBe(12345)
  expect(restored.settings.describe().find(row => row.ns === 'tool-audio-transcription')?.value).toMatchObject({ baseUrl: 'http://voice:7070', model: 'sensevoice-int8' })
})
