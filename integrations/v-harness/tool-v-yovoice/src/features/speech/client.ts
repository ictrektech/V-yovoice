/** TTS catalogue parsing and bounded speech transport. */
import { HarnessError } from '@deepseek-ai/dsh-llm'
import { requestServiceAudio, requestServiceJson, ServiceRequestError } from '../../core/service.ts'
import type { VoiceConfig } from '../../core/config.ts'
import type { SpeechModel, SpeechVoice } from '../../types.ts'

function speechFailure(cause: unknown, signal: AbortSignal, pageCharacters: number): never {
  signal.throwIfAborted()
  if (cause instanceof HarnessError) throw cause
  if (cause instanceof ServiceRequestError) {
    const detail = cause.options.detail && cause.options.detail.length > pageCharacters
      ? `${cause.options.detail.slice(0, pageCharacters)}… (service error detail shortened)`
      : cause.options.detail ?? ''
    const status = cause.options.status === undefined
      ? ''
      : `HTTP ${cause.options.status}${cause.options.serviceCode ? `; ${cause.options.serviceCode}` : ''}`
    if (cause.options.status === 429) {
      throw new HarnessError(`V-yovoice is busy: the compute scheduler refused admission (${status})${detail ? `: ${detail}` : ''}. No speech was saved; retry only when resources are available.`, 'AUDIO_SERVICE_BUSY', { cause })
    }
    if (cause.options.status === 409) {
      throw new HarnessError(`V-yovoice TTS model is not ready (${status})${detail ? `: ${detail}` : ''}.`, 'AUDIO_MODEL_NOT_READY', { cause })
    }
    if (cause.options.status === 404) {
      throw new HarnessError(`V-yovoice could not find the TTS model or voice (${status})${detail ? `: ${detail}` : ''}. Refresh the plugin catalogue and retry once.`, 'AUDIO_INVALID_CONFIG', { cause })
    }
    if (cause.options.status === 413) {
      throw new HarnessError(`V-yovoice rejected the speech input (${status})${detail ? `: ${detail}` : ''}. No audio was saved.`, 'AUDIO_TOO_LARGE', { cause })
    }
    if (cause.code === 'response_too_large') {
      throw new HarnessError('V-yovoice speech response exceeds maxSpeechBytes; no audio was saved.', 'AUDIO_RESPONSE_TOO_LARGE', { cause })
    }
    if (cause.code === 'invalid_response') {
      throw new HarnessError(`V-yovoice returned an invalid speech response${detail ? `: ${detail}` : ''}.`, 'AUDIO_INVALID_RESPONSE', { cause })
    }
    if (cause.options.status !== undefined) {
      throw new HarnessError(`V-yovoice speech request failed (${status})${detail ? `: ${detail}` : ''}; no audio was saved.`, 'AUDIO_SERVICE_ERROR', { cause })
    }
    throw new HarnessError(cause.options.outcomeUnknown
      ? 'V-yovoice is unreachable or the request timed out. The remote speech outcome is unknown; no audio was saved. Report the error; do not retry automatically.'
      : 'V-yovoice is unreachable or the request timed out. No speech request was submitted.', 'AUDIO_SERVICE_UNAVAILABLE', { cause })
  }
  throw cause
}

/** Fetch one bounded JSON document with speech-specific failures. */
export async function speechJson(config: VoiceConfig, path: string, signal: AbortSignal): Promise<unknown> {
  try {
    return await requestServiceJson(config, path, signal)
  } catch (cause) {
    speechFailure(cause, signal, config.pageCharacters)
  }
}

/** Stream one synthesized WAV and preserve cancellation and service errors. */
export async function speechAudio(
  config: VoiceConfig,
  payload: Record<string, unknown>,
  signal: AbortSignal,
): Promise<AsyncIterable<Uint8Array>> {
  try {
    return await requestServiceAudio(config, '/v1/audio/speech', signal, payload, config.maxSpeechBytes)
  } catch (cause) {
    speechFailure(cause, signal, config.pageCharacters)
  }
}

/** Parse ready and unavailable TTS models from the managed model catalogue. */
export function speechModelRows(value: unknown): SpeechModel[] {
  if (!Array.isArray(value)) throw new HarnessError('V-yovoice returned an invalid model catalogue', 'AUDIO_INVALID_RESPONSE')
  return value.flatMap((row: unknown) => {
    if (typeof row !== 'object' || row === null || !('kind' in row) || row.kind !== 'tts') return []
    if (!('key' in row) || typeof row.key !== 'string' || !('name' in row) || typeof row.name !== 'string') {
      throw new HarnessError('V-yovoice returned an invalid TTS model', 'AUDIO_INVALID_RESPONSE')
    }
    const capabilities = 'capabilities' in row && Array.isArray(row.capabilities)
      ? row.capabilities.filter((item): item is string => typeof item === 'string')
      : []
    const languages = 'languages' in row && Array.isArray(row.languages)
      ? row.languages.filter((item): item is string => typeof item === 'string')
      : []
    const voices: SpeechVoice[] = []
    if ('voices' in row && typeof row.voices === 'object' && row.voices !== null && !Array.isArray(row.voices)) {
      for (const [id, raw] of Object.entries(row.voices as Record<string, unknown>)) {
        const descriptor: unknown = raw
        const languageValue = typeof descriptor === 'object' && descriptor !== null && 'language' in descriptor
          ? descriptor['language']
          : undefined
        const language = typeof languageValue === 'string' ? languageValue : ''
        voices.push({ id, name: id, ...(language === '' ? {} : { language }) })
      }
    }
    return [{
      key: row.key,
      name: row.name,
      ready: 'status' in row && row.status === 'ready',
      languages,
      capabilities,
      voices,
    }]
  })
}

/** Parse the voice IDs that the selected TTS model accepts. */
export function voiceRows(value: unknown, model: string): SpeechVoice[] {
  if (typeof value !== 'object' || value === null || !('model' in value) || value.model !== model
    || !('voices' in value) || !Array.isArray(value.voices)) {
    throw new HarnessError('V-yovoice returned an invalid voice catalogue', 'AUDIO_INVALID_RESPONSE')
  }
  return value.voices.map((row: unknown) => {
    if (typeof row !== 'object' || row === null || !('id' in row) || typeof row.id !== 'string'
      || !('name' in row) || typeof row.name !== 'string') {
      throw new HarnessError('V-yovoice returned an invalid TTS voice', 'AUDIO_INVALID_RESPONSE')
    }
    return {
      id: row.id,
      name: row.name,
      ...('language' in row && typeof row.language === 'string' && row.language !== '' ? { language: row.language } : {}),
    }
  })
}
