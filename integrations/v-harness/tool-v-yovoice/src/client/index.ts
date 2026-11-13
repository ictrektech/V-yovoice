/** Installable UI and Remote assembly, independent of the host's fixed API roster. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-settings/client'
import type {} from '@deepseek-ai/dsh-client-ui-plugin-manager/client'
import type {} from '@deepseek-ai/dsh-client-ui-tool/client'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-chat/client'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import contribution from '@ictrek/dsh-tool-v-yovoice/remote'
import { audioForm, type AudioSettings } from './form.ts'
import { AudioSettingsView, AudioTranscriptView, AudioTurnOriginals, type AudioTurnOriginalsInjected } from './Views.tsx'
import { audioTurnDefinition } from './turn.ts'
import { NS, en, zh } from './locales.ts'

/** Services supplied by the Web or Desktop host. */
export const inject = ['remote', 'slots', 'locale', 'configForms', 'uiConversation']
/**
 * Mount this package's own Remote contribution, configuration page and result card.
 * @param ctx - browser plugin scope.
 * @returns disposer withdrawing all UI and Remote registrations.
 */
export async function apply(ctx: Context): Promise<() => Promise<void>> {
  const disposeRemote = await ctx.remote.$mount(contribution)
  const ui = ctx.inject(['remote.audioTranscription'], (child) => {
    child.effect(() => child.locale.register(NS, { en, zh }))
    const config = audioForm(child.configForms.get<AudioSettings>('tool-audio-transcription'))
    child.effect(() => () => { config.form.dispose() })
    child.slots.inject('plugins.bundle.config', () => child.slots.register({
      name: 'plugins.bundle.config', key: '@ictrek/dsh-tool-v-yovoice', locale: NS,
      inject: () => ({ hooks: { audioSettings: config.store }, ...config.actions, catalog: async (signal: AbortSignal) => {
        const result = await child.remote.audioTranscription.catalog(signal)
        if (!result.ok) throw result.error
        return result.value
      } }),
    }, AudioSettingsView))
    child.slots.inject('tool.call.toolview', () => child.slots.register({ name: 'tool.call.toolview', key: 'transcribe_audio', locale: NS }, AudioTranscriptView))
    child.effect(() => child.uiConversation.events.register(audioTurnDefinition))
    child.slots.inject('conversation.chat.turnTail', () => child.slots.register({
      name: 'conversation.chat.turnTail', id: 'audio-originals', order: 20, locale: NS,
      inject: (sessionId: SessionId): AudioTurnOriginalsInjected => ({
        sessionId,
        savedTranscript: async (source, signal) => {
          const result = await child.remote.audioTranscription.savedTranscript(String(sessionId), source, signal)
          if (!result.ok) throw result.error
          return result.value
        },
      }),
    }, AudioTurnOriginals))
  })
  try { await ui } catch (error) { await ui.dispose(); await disposeRemote(); throw error }
  return async () => { await ui.dispose(); await disposeRemote() }
}
