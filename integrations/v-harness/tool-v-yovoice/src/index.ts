/** Single installable V-yovoice plugin with compatibility-preserving transcription support. */
import type { Context, Volatile } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-settings'
import z from '@deepseek-ai/schemastery'
import { AudioController } from './features/transcription/controller.ts'
import { registerTranscription } from './features/transcription/index.ts'
import { CapabilityRegistry } from './core/capability.ts'
import { resolveConfig } from './core/config.ts'
import { registerAudioProjection } from './core/projection.ts'
import { serveNodeAudio } from './core/playback.ts'
import { AUDIO_PLAYBACK_PATH } from './core/playback-route.ts'

export { AudioController } from './features/transcription/controller.ts'

/**
 * Keep the established Loader identity for the first umbrella release.
 * The settings profile and persisted configuration are keyed by this id, so
 * changing it here would make existing users configure the plugin again.
 */
export const name = 'tool-audio-transcription'

/** Services owning tools, durable attachments, authenticated streaming and execution-world file access. */
export const inject = ['tools', 'attachments', 'fs', 'sessionProjections', 'systemPrompt', 'connection', 'webServer']

/** Deployment-owned endpoint, fixed ASR model, request deadline and acquisition/display bounds. */
export interface Config {
  /** VOS V-yovoice service root, empty until configured. */
  baseUrl: Volatile<string>
  /** Explicit ASR model key, empty until selected. */
  model: Volatile<string>
  /** Complete request deadline in milliseconds. */
  requestTimeoutMs: Volatile<number>
  /** Maximum acquired audio bytes before service limits apply. */
  maxUploadBytes: Volatile<number>
  /** Maximum bytes in a service JSON response. */
  maxResponseBytes: Volatile<number>
  /** UTF-16 characters in one model-visible transcript window. */
  pageCharacters: Volatile<number>
}

/** Validated Loader configuration. */
export const Config = z.object({
  baseUrl: z.string().pattern(/^(?:https?:\/\/[^/?#@\s]+(?:\/[^?#\s]*)?)?$/u).default('').volatile(),
  model: z.string().default('').volatile(),
  requestTimeoutMs: z.natural().min(1).max(2_147_483_647).default(1_860_000).volatile(),
  maxUploadBytes: z.natural().min(1).max(2_147_483_647).default(209_715_200).volatile(),
  maxResponseBytes: z.natural().min(1).max(2_147_483_647).default(16_777_216).volatile(),
  pageCharacters: z.natural().min(1).max(2_147_483_647).default(12_000).volatile(),
})

/**
 * Mount the shared V-yovoice base and the transcription capability.
 * @param ctx - plugin scope owning tools, persistence and playback.
 * @param config - current profile settings.
 */
export async function apply(ctx: Context, config: Config): Promise<void> {
  const lifetime = new AbortController()
  ctx.effect(() => () => { lifetime.abort(new Error('V-yovoice plugin unloaded')) })

  const options = () => ({
    baseUrl: config.baseUrl.get(),
    model: config.model.get(),
    requestTimeoutMs: config.requestTimeoutMs.get(),
    maxUploadBytes: config.maxUploadBytes.get(),
    maxResponseBytes: config.maxResponseBytes.get(),
    pageCharacters: config.pageCharacters.get(),
  })
  const current = () => resolveConfig(options())
  const catalog = () => resolveConfig(options(), false)

  const projection = await registerAudioProjection(ctx)
  const capabilities = new CapabilityRegistry()
  capabilities.register({ id: 'transcription', available: true })

  ctx.inject(['typert'], (child) => {
    new AudioController(child, catalog, lifetime.signal, projection)
  })
  ctx.inject(['settings'], (child) => {
    child.settings.configure({ auto: false }, ctx.fiber)
  })
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: AUDIO_PLAYBACK_PATH,
    handler: (req, res) => serveNodeAudio(ctx, req, res, lifetime.signal, projection),
  }), 'tool-v-yovoice: session-audio playback')

  if (capabilities.list().some(item => item.id === 'transcription' && item.available)) {
    registerTranscription(ctx, projection, {
      current,
      catalog,
      pageCharacters: () => config.pageCharacters.get(),
      requestTimeoutMs: () => config.requestTimeoutMs.get(),
      signal: lifetime.signal,
    })
  }
}
