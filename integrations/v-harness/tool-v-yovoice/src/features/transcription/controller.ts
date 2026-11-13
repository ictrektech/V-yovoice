/** Plugin-owned, authenticated model discovery; decoding remains with V-yovoice. */
import type { AudioCatalog, AudioSavedTranscript } from '../../types.ts'
import type { Context } from '@deepseek-ai/cordis'
import { Remote, RemoteError, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import { brandString } from '@deepseek-ai/dsh-brand'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import { audioStateOfSession, type AudioProjection } from '../../core/projection.ts'
import { modelRows, voiceJson, type VoiceConfig } from './client.ts'

declare module '@deepseek-ai/cordis' {
  interface Context {
    /** The installed audio plugin's model catalogue. */
    audioTranscription: AudioController
  }
}

/** Remote discovery owned and withdrawn by this plugin's Loader scope. */
export class AudioController extends TypertRemoteService {
  /**
   * @param ctx - plugin context with the authenticated Typert gateway.
   * @param options - current profile settings, resolved at request admission.
   * @param lifetime - plugin disposal cancellation.
   * @param projection - registered session projection.
   */
  constructor(
    ctx: Context, private readonly options: () => VoiceConfig,
    private readonly lifetime: AbortSignal, private readonly projection: AudioProjection,
  ) {
    super(ctx, 'audioTranscription')
  }

  /**
   * Query the saved service address without submitting any inference job.
   * @param signal - browser request cancellation.
   * @returns ASR identities and the profile's selected model.
   */
  @Remote
  async catalog(signal: AbortSignal): Promise<AudioCatalog> {
    try {
      const config = this.options()
      return { selected: config.model, models: modelRows(await voiceJson(config, '/api/v1/models', AbortSignal.any([signal, this.lifetime]))) }
    } catch (cause) {
      signal.throwIfAborted()
      throw new RemoteError('gateway/internal', cause instanceof Error ? cause.message : String(cause), {}, { cause })
    }
  }

  /**
   * Restore the latest successful text for one source in the selected session.
   * @param sessionId - exact session whose projection owns the transcript.
   * @param source - SHA-256 source identity returned by the transcription tool.
   * @param signal - browser request cancellation.
   * @returns latest saved transcript, or null when none exists.
   */
  @Remote
  savedTranscript(sessionId: string, source: string, signal: AbortSignal): AudioSavedTranscript | null {
    try {
      signal.throwIfAborted()
      const sessions = this.ctx.get('sessions')
      if (sessions === undefined) return null
      const session = sessions.get(brandString<SessionId>(sessionId))
      if (session === undefined) return null
      const state = audioStateOfSession(this.projection, session)
      const saved = state.transcripts.findLast(row => row.source === source)
      if (saved === undefined) return null
      const attachment = state.files.find(file => file.id === `sha256:${source}`)
      return {
        source: saved.source,
        file: saved.file,
        model: saved.model,
        text: saved.text,
        ...(attachment === undefined ? {} : { attachmentId: attachment.id }),
      }
    } catch (cause) {
      signal.throwIfAborted()
      throw new RemoteError('gateway/internal', cause instanceof Error ? cause.message : String(cause), {}, { cause })
    }
  }
}
