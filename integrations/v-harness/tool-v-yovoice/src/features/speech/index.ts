/** Text-to-speech through the configured V-yovoice public API. */
import type {} from '@deepseek-ai/dsh-system-prompt'
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-client-connection'
import { HarnessError } from '@deepseek-ai/dsh-llm'
import { speechArtifact } from '../../core/artifact.ts'
import type { VoiceConfig } from '../../core/config.ts'
import { completedOperation } from '../../core/operation.ts'
import type { SpeechModel, SpeechVoice } from '../../types.ts'
import { speechAudio, speechJson, speechModelRows, voiceRows } from './client.ts'

/** Live speech settings and plugin lifetime. */
export interface SpeechRuntime {
  /** Settings that require a configured TTS model and voice. */
  speech(): VoiceConfig
  /** Base settings used for catalogue discovery without requiring an ASR model. */
  catalog(): VoiceConfig
  /** Service error detail truncation. */
  pageCharacters(): number
  /** Tool timeout shown to DSH. */
  requestTimeoutMs(): number
  /** Plugin unload cancellation shared by active requests. */
  signal: AbortSignal
}

const TEXT_OUTPUT = { schema: { type: 'string' as const }, render: (_args: unknown, text: string) => [{ type: 'text' as const, text }] }
const MAX_TEXT_CHARACTERS = 20_000
const MAX_OPTION_CHARACTERS = 500

function characterCount(value: string): number {
  return Array.from(value).length
}

function modelCapability(model: SpeechModel, capability: string): boolean {
  return model.capabilities.includes(capability)
}

function compactTime(): string {
  return new Date().toISOString().replace(/[-:]/gu, '').replace('T', '-').replace(/\..+$/u, '')
}

async function loadModel(
  config: VoiceConfig,
  signal: AbortSignal,
): Promise<SpeechModel> {
  const models = speechModelRows(await speechJson(config, '/api/v1/models', signal))
  const model = models.find(item => item.key === config.speechModel)
  if (model === undefined) throw new HarnessError('The configured V-yovoice TTS model was not found. Refresh the plugin catalogue.', 'AUDIO_INVALID_CONFIG')
  if (!model.ready) throw new HarnessError('The configured V-yovoice TTS model is not ready. Ask the administrator to prepare it.', 'AUDIO_MODEL_NOT_READY')
  return model
}

async function loadVoices(config: VoiceConfig, signal: AbortSignal): Promise<SpeechVoice[]> {
  const voices = voiceRows(await speechJson(config, `/v1/audio/voices?model=${encodeURIComponent(config.speechModel)}`, signal), config.speechModel)
  if (voices.length === 0) throw new HarnessError('V-yovoice returned no voices for the configured TTS model.', 'AUDIO_INVALID_RESPONSE')
  return voices
}

function selectedVoice(config: VoiceConfig, requested: string | undefined, voices: SpeechVoice[]): string {
  const voice = requested?.trim() || config.speechVoice
  if (!voice) throw new HarnessError('Select a TTS voice in the plugin page or pass an advertised voice ID.', 'AUDIO_NOT_CONFIGURED')
  if (!voices.some(item => item.id === voice)) {
    const available = voices.slice(0, 20).map(item => item.id).join(', ')
    throw new HarnessError(`Voice ${voice} is not available for model ${config.speechModel}. Available IDs: ${available}${voices.length > 20 ? ', …' : ''}`, 'AUDIO_INVALID_VOICE')
  }
  return voice
}

/**
 * Register TTS catalogue lookup and synthesis.
 * @param ctx - plugin scope owning tools and attachments.
 * @param runtime - current speech settings and plugin cancellation.
 */
export function registerSpeech(ctx: Context, runtime: SpeechRuntime): void {
  ctx.systemPrompt.section({
    name: 'tool:v-yovoice-speech', order: ctx.systemPrompt.getSectionOrder('TOOL_READ'),
    text: 'When the user asks to speak, read aloud, synthesize, or create a voice-over from supplied text, call yovoice_speak with the exact text they want spoken. '
      + 'Do not substitute a summary, translation, or rewritten script. Do not call transcribe_audio for text-to-speech. '
      + 'The plugin uses the configured TTS model; the user may override only its advertised voice and supported generation options. '
      + 'Call yovoice_voices only when the user asks which voices are available, requests a specific voice or language, or the configured voice is rejected. '
      + 'Pass voice_description only for voice-design models and emotion_text only for emotion-control models. '
      + 'A successful result is saved as a conversation attachment and shown in a playback card; do not invent audio URLs or write local file paths. '
      + 'If synthesis fails or the service is busy, report the error and stop without retrying automatically.',
  })
  ctx.tools.register(defineTool({
    name: 'yovoice_voices',
    description: 'List the voices available for the configured V-yovoice TTS model. Use only when the user asks about voices or requests a voice/language, not before every speech generation.',
    parameters: {
      language: { type: 'string', description: 'Optional language code such as zh or en to narrow the advertised voices.' },
    },
    output: TEXT_OUTPUT,
    async execute(args, exec) {
      const config = runtime.catalog()
      if (!config.speechModel) throw new HarnessError('Select a TTS model in the plugin page.', 'AUDIO_NOT_CONFIGURED')
      const signal = AbortSignal.any([exec.signal, runtime.signal, AbortSignal.timeout(runtime.requestTimeoutMs())])
      const model = speechModelRows(await speechJson(config, '/api/v1/models', signal)).find(item => item.key === config.speechModel)
      if (model === undefined) throw new HarnessError('The configured V-yovoice TTS model was not found.', 'AUDIO_INVALID_CONFIG')
      const voices = await loadVoices(config, signal)
      const requestedLanguage = args.language?.trim() ?? ''
      const matching = requestedLanguage === '' ? voices : voices.filter(item => item.language === requestedLanguage)
      return JSON.stringify({
        model: { key: model.key, name: model.name, ready: model.ready, languages: model.languages, capabilities: model.capabilities },
        selected_voice: config.speechVoice,
        language: requestedLanguage || null,
        language_matched: requestedLanguage === '' || matching.length > 0,
        voices: matching.length > 0 ? matching : voices,
      })
    },
  }))
  const speak = defineTool({
    name: 'yovoice_speak',
    description: 'Generate speech from exact user-supplied text with the configured V-yovoice TTS model. Use this for reading aloud, speech synthesis, narration and voice-over requests. Returns a durable WAV attachment and a playback card; audio bytes never enter the model request.',
    parameters: {
      text: { type: 'string', required: true, description: 'Exact text to speak, without model-added summaries or commentary. Maximum 20,000 characters.' },
      voice: { type: 'string', description: 'Optional advertised voice ID for the configured model. Omit to use the plugin default.' },
      language: { type: 'string', description: 'Optional language code; empty uses the model or voice default.' },
      speed: { type: 'number', description: 'Speech speed from 0.25 to 4.0; default 1.0.' },
      voice_description: { type: 'string', description: 'Voice-design instruction for models advertising voice_design or voice_instruction. Maximum 500 characters.' },
      emotion_text: { type: 'string', description: 'Emotion instruction for models advertising emotion_control. Maximum 500 characters.' },
      emotion_strength: { type: 'number', description: 'Emotion strength from 0 to 1; valid only with emotion_text.' },
    },
    output: {
      schema: { type: 'object', additionalProperties: false, properties: {
        attachmentId: { type: 'string', required: true }, file: { type: 'string', required: true },
        model: { type: 'string', required: true }, voice: { type: 'string', required: true },
        text: { type: 'string', required: true }, bytes: { type: 'number', required: true },
        language: { type: 'string' },
      } },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify({
        file: value.file, model: value.model, voice: value.voice, bytes: value.bytes,
        message: 'Speech generated and saved as a conversation attachment. Playback is available in the result card.',
      }) }],
      presentationMeta: (_args, value) => {
        const source = value.attachmentId.replace(/^sha256:/u, '')
        return {
          ...value,
          audioSpeech: true,
          artifact: speechArtifact({ source, model: value.model, voice: value.voice }),
          operation: { ...completedOperation('speech', `speech:${source}`) },
        }
      },
    },
    presentCall: args => ({ card: 'generic', title: 'yovoice_speak', rawInput: args }),
    async execute(args, exec) {
      const config = runtime.speech()
      const text = args.text
      if (text.trim() === '') throw new HarnessError('Speech text must not be empty.', 'AUDIO_INVALID_SOURCE')
      if (characterCount(text) > MAX_TEXT_CHARACTERS) throw new HarnessError('Speech text exceeds 20,000 characters.', 'AUDIO_TOO_LARGE')
      const speed = args.speed ?? 1
      if (!Number.isFinite(speed) || speed < 0.25 || speed > 4) throw new HarnessError('Speech speed must be between 0.25 and 4.0.', 'AUDIO_INVALID_CONFIG')
      const language = args.language?.trim() ?? ''
      if (characterCount(language) > 32) throw new HarnessError('Speech language must be 32 characters or fewer.', 'AUDIO_INVALID_CONFIG')
      const voiceDescription = args.voice_description?.trim() ?? ''
      const emotionText = args.emotion_text?.trim() ?? ''
      if (characterCount(voiceDescription) > MAX_OPTION_CHARACTERS) throw new HarnessError('voice_description exceeds 500 characters.', 'AUDIO_INVALID_CONFIG')
      if (characterCount(emotionText) > MAX_OPTION_CHARACTERS) throw new HarnessError('emotion_text exceeds 500 characters.', 'AUDIO_INVALID_CONFIG')
      if (args.emotion_strength !== undefined && emotionText === '') throw new HarnessError('emotion_strength requires emotion_text.', 'AUDIO_INVALID_CONFIG')
      const emotionStrength = args.emotion_strength ?? 0.6
      if (!Number.isFinite(emotionStrength) || emotionStrength < 0 || emotionStrength > 1) {
        throw new HarnessError('emotion_strength must be between 0 and 1.', 'AUDIO_INVALID_CONFIG')
      }
      const signal = AbortSignal.any([exec.signal, runtime.signal, AbortSignal.timeout(runtime.requestTimeoutMs())])
      const [model, voices] = await Promise.all([loadModel(config, signal), loadVoices(config, signal)])
      if (voiceDescription !== '' && !modelCapability(model, 'voice_design') && !modelCapability(model, 'voice_instruction')) {
        throw new HarnessError(`Model ${model.key} does not support voice_description.`, 'AUDIO_UNSUPPORTED_OPTION')
      }
      if (emotionText !== '' && !modelCapability(model, 'emotion_control')) {
        throw new HarnessError(`Model ${model.key} does not support emotion controls.`, 'AUDIO_UNSUPPORTED_OPTION')
      }
      const voice = selectedVoice(config, args.voice, voices)
      const file = `speech-${compactTime()}.wav`
      const stream = await speechAudio(config, {
        model: config.speechModel,
        input: text,
        voice,
        response_format: 'wav',
        speed,
        ...(language === '' ? {} : { language }),
        ...(voiceDescription === '' ? {} : { voice_description: voiceDescription }),
        ...(emotionText === '' ? {} : { emotion_text: emotionText, emotion_strength: emotionStrength }),
      }, signal)
      const stored = await ctx.attachments.saveFileStream({ name: file, data: stream, signal })
      signal.throwIfAborted()
      return {
        attachmentId: String(stored.attachmentId), file: stored.name, model: config.speechModel,
        voice, text, bytes: stored.bytes, ...(language === '' ? {} : { language }),
      }
    },
  })
  ctx.tools.register({ ...speak, get timeoutMs() { return runtime.requestTimeoutMs() } })
}
