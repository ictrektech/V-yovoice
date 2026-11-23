/** Shared service and capability limits used by every V-yovoice feature. */
import { HarnessError } from '@deepseek-ai/dsh-llm'

/** Resolved endpoint and resource bounds shared by service requests. */
export interface VoiceConfig {
  /** HTTP(S) service root without /v1. */
  baseUrl: string
  /** Selected ASR model key for the transcription capability. */
  model: string
  /** Selected TTS model key for the speech capability. */
  speechModel: string
  /** Default voice ID for the selected TTS model. */
  speechVoice: string
  /** Maximum time in milliseconds for each request. */
  requestTimeoutMs: number
  /** Deployment cap on acquired audio bytes. */
  maxUploadBytes: number
  /** Deployment cap on one generated speech file. */
  maxSpeechBytes: number
  /** Maximum UTF-16 characters in one model-visible result window. */
  pageCharacters: number
  /** Maximum bytes in a complete service JSON response. */
  maxResponseBytes: number
  /** Maximum dictation recording duration in whole seconds. */
  maxDictationSeconds: number
}

/** Input accepted by the first compatibility release. */
export interface ConfigInput extends Partial<VoiceConfig> {
  /** Capability-specific defaults introduced for later modules. */
  defaults?: {
    transcription?: { model?: string }
    speech?: { model?: string; voice?: string }
    score?: { soundFont?: string }
    music?: { model?: string }
  }
}

/**
 * Validate deployment settings before advertising tools.
 * @param config - explicit service defaults plus optional deployment bounds.
 * @param requireModel - require a selected transcription model.
 * @returns validated settings with defaults resolved.
 */
export function resolveConfig(config: ConfigInput, requireModel = true): VoiceConfig {
  const resolved = resolveBaseConfig(config)
  const model = config.model?.trim() ? config.model : config.defaults?.transcription?.model ?? ''
  if (requireModel && !model.trim()) {
    throw new HarnessError('Select an ASR model in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  }
  return { ...resolved, model }
}

/**
 * Resolve the selected TTS model and voice without requiring an ASR model.
 * @param config - explicit speech defaults plus optional deployment bounds.
 * @returns validated settings for speech synthesis.
 */
export function resolveSpeechConfig(config: ConfigInput): VoiceConfig {
  const resolved = resolveBaseConfig(config)
  const speechModel = config.speechModel?.trim() ? config.speechModel : config.defaults?.speech?.model ?? ''
  const speechVoice = config.speechVoice?.trim() ? config.speechVoice : config.defaults?.speech?.voice ?? ''
  if (!speechModel.trim()) {
    throw new HarnessError('Select a TTS model in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  }
  if (!speechVoice.trim()) {
    throw new HarnessError('Select a default TTS voice in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  }
  return { ...resolved, model: '', speechModel, speechVoice }
}

function resolveBaseConfig(config: ConfigInput): VoiceConfig {
  if (!config.baseUrl?.trim()) {
    throw new HarnessError('Configure the V-yovoice service address in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  }
  let baseUrl: URL
  try {
    baseUrl = new URL(config.baseUrl)
  } catch (cause) {
    throw new HarnessError('V-yovoice service address must be an HTTP(S) URL.', 'AUDIO_INVALID_CONFIG', { cause })
  }
  if (!['http:', 'https:'].includes(baseUrl.protocol) || baseUrl.username || baseUrl.password || baseUrl.search || baseUrl.hash) {
    throw new Error('audio-transcription: baseUrl must be an HTTP(S) service root without credentials, query or fragment')
  }
  const resolved = {
    baseUrl: baseUrl.href.replace(/\/+$/u, ''),
    model: '',
    speechModel: config.speechModel?.trim() ?? '',
    speechVoice: config.speechVoice?.trim() ?? '',
    requestTimeoutMs: config.requestTimeoutMs ?? 1_860_000,
    maxUploadBytes: config.maxUploadBytes ?? 200 * 1024 * 1024,
    maxSpeechBytes: config.maxSpeechBytes ?? 256 * 1024 * 1024,
    pageCharacters: config.pageCharacters ?? 12_000,
    maxResponseBytes: config.maxResponseBytes ?? 16 * 1024 * 1024,
    maxDictationSeconds: config.maxDictationSeconds ?? 120,
  }
  for (const [key, value] of Object.entries(resolved)) {
    if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 1 || value > 2_147_483_647)) {
      throw new Error(`audio-transcription: ${key} must be a positive integer within timer/buffer limits`)
    }
  }
  return resolved
}
