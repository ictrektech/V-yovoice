/** Session-independent dictation recognition through the configured V-yovoice ASR model. */
import { HarnessError } from '@deepseek-ai/dsh-llm'
import type { VoiceConfig } from '../../core/config.ts'
import { validateDictationWave } from '../../core/wav.ts'
import type { DictationLimits, DictationRequest, DictationResult } from '../../types.ts'
import { modelRows, transcriptText, uploadLimit, voiceJson } from '../transcription/client.ts'

const PCM16_BYTES_PER_SECOND = 16_000 * 2

/** Derive the shared client/Host recording limit from the WAV duration bound. */
export function dictationLimits(config: VoiceConfig): DictationLimits {
  return {
    maxSeconds: config.maxDictationSeconds,
    maxAudioBytes: Math.min(config.maxUploadBytes, 44 + config.maxDictationSeconds * PCM16_BYTES_PER_SECOND),
  }
}

function decodeRequest(config: VoiceConfig, request: DictationRequest): Uint8Array<ArrayBuffer> {
  if (typeof request.audioBase64 !== 'string') {
    throw new HarnessError('Dictation audio must be base64 encoded.', 'AUDIO_INVALID_SOURCE')
  }
  const encoded = request.audioBase64
  const maxBytes = dictationLimits(config).maxAudioBytes
  if (encoded.length > 4 * Math.ceil(maxBytes / 3)) {
    throw new HarnessError('Dictation recording exceeds the configured byte limit.', 'AUDIO_TOO_LARGE')
  }
  const decoded = Buffer.from(encoded, 'base64')
  if (decoded.toString('base64') !== encoded) {
    throw new HarnessError('Dictation audio must use canonical base64 encoding.', 'AUDIO_INVALID_SOURCE')
  }
  if (decoded.byteLength > maxBytes) {
    throw new HarnessError('Dictation recording exceeds the configured byte limit.', 'AUDIO_TOO_LARGE')
  }
  const audio = new Uint8Array(decoded)
  validateDictationWave(audio, config.maxDictationSeconds)
  return audio
}

/**
 * Recognize one complete browser recording without creating a Session event.
 * @param config - current ASR model and service bounds.
 * @param request - canonical base64 PCM16 WAV.
 * @param signal - browser or plugin cancellation.
 * @returns verbatim text for explicit insertion into the draft.
 */
export async function transcribeDictation(
  config: VoiceConfig,
  request: DictationRequest,
  signal: AbortSignal,
): Promise<DictationResult> {
  signal.throwIfAborted()
  const audio = decodeRequest(config, request)
  const [catalogue, capabilities] = await Promise.all([
    voiceJson(config, '/api/v1/models', signal),
    voiceJson(config, `/api/v1/models/${encodeURIComponent(config.model)}/input-limits`, signal),
  ])
  if (!modelRows(catalogue).some(model => model.key === config.model && model.ready)) {
    throw new HarnessError('The configured V-yovoice ASR model is not inference-ready.', 'AUDIO_MODEL_NOT_READY')
  }
  const serviceLimit = uploadLimit(capabilities, dictationLimits(config).maxAudioBytes)
  if (audio.byteLength > serviceLimit) {
    throw new HarnessError('Dictation recording exceeds the model upload limit.', 'AUDIO_TOO_LARGE')
  }

  const form = new FormData()
  form.set('file', new Blob([audio], { type: 'audio/wav' }), 'dictation.wav')
  form.set('model', config.model)
  form.set('language', '')
  form.set('response_format', 'json')
  const response = await voiceJson(config, '/v1/audio/transcriptions', signal, form)
  signal.throwIfAborted()
  return { text: transcriptText(response), model: config.model }
}
