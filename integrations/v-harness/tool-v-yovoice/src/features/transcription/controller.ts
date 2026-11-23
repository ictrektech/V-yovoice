/** Plugin-owned, authenticated model discovery; decoding remains with V-yovoice. */
import type { AudioCatalog, AudioSavedTranscript } from '../../types.ts'
import type { Context } from '@deepseek-ai/cordis'
import { Remote, RemoteError, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import { brandString } from '@deepseek-ai/dsh-brand'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import { audioStateOfSession, type AudioProjection } from '../../core/projection.ts'
import { dictationLimits, transcribeDictation } from '../dictation/index.ts'
import type { DictationLimits, DictationRequest, DictationResult } from '../../types.ts'
import { modelRows, voiceJson, type VoiceConfig } from './client.ts'
import { speechModelRows } from '../speech/client.ts'

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
   * @param current - settings that require a selected ASR model.
   * @param lifetime - plugin disposal cancellation.
   * @param projection - registered session projection.
   */
  constructor(
    ctx: Context, private readonly options: () => VoiceConfig, private readonly current: () => VoiceConfig,
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
      const rows = await voiceJson(config, '/api/v1/models', AbortSignal.any([signal, this.lifetime]))
      const speechModels = speechModelRows(rows)
      const selectedSpeech = speechModels.find(model => model.key === config.speechModel)
      return {
        selected: config.model,
        models: modelRows(rows),
        speech: {
          selectedModel: config.speechModel,
          selectedVoice: config.speechVoice,
          models: speechModels,
          voices: selectedSpeech?.voices ?? [],
        },
      }
    } catch (cause) {
      signal.throwIfAborted()
      throw new RemoteError('gateway/internal', cause instanceof Error ? cause.message : String(cause), {}, { cause })
    }
  }

  /**
   * Read the current dictation duration and byte bounds without inference.
   * @param signal - browser request cancellation.
   * @returns bounds derived from the configured ASR model and profile limits.
   */
  @Remote
  dictationLimits(signal: AbortSignal): DictationLimits {
    try {
      signal.throwIfAborted()
      return dictationLimits(this.current())
    } catch (cause) {
      signal.throwIfAborted()
      throw new RemoteError('gateway/internal', cause instanceof Error ? cause.message : String(cause), {}, { cause })
    }
  }

  /**
   * Recognize one transient microphone recording for the unsent composer draft.
   * @param request - canonical base64 PCM16 WAV.
   * @param signal - browser cancellation.
   * @returns verbatim text; no Session event or attachment is created.
   */
  @Remote
  async transcribeDictation(request: DictationRequest, signal: AbortSignal): Promise<DictationResult> {
    const combined = AbortSignal.any([signal, this.lifetime])
    try {
      return await transcribeDictation(this.current(), request, combined)
    } catch (cause) {
      combined.throwIfAborted()
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
