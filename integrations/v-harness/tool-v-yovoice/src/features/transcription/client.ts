/** V-yovoice HTTP transport; audio decoding and calibrated limits remain service-owned. */
import { HarnessError } from '@deepseek-ai/dsh-llm'
import { requestServiceJson, ServiceRequestError } from '../../core/service.ts'
import type { VoiceConfig } from '../../core/config.ts'

export { resolveConfig } from '../../core/config.ts'
export type { VoiceConfig } from '../../core/config.ts'

/** Fetch a bounded JSON response, propagate cancellation and reject HTTP errors.
 * @param config - validated deployment settings.
 * @param path - service-relative endpoint.
 * @param signal - caller cancellation.
 * @param body - multipart upload for POST; omitted for GET.
 * @returns decoded wire data for operation-specific validation.
 */
export async function voiceJson(config: VoiceConfig, path: string, signal: AbortSignal, body?: FormData): Promise<unknown> {
  try {
    return await requestServiceJson(config, path, signal, body)
  } catch (cause) {
    signal.throwIfAborted()
    if (cause instanceof HarnessError) throw cause
    if (cause instanceof ServiceRequestError) {
      const detail = cause.options.detail && cause.options.detail.length > config.pageCharacters
        ? cause.options.detail.slice(0, config.pageCharacters) + '… (service error detail shortened)'
        : cause.options.detail ?? ''
      if (cause.options.status === 429) {
        const status = `HTTP 429${cause.options.serviceCode ? `; ${cause.options.serviceCode}` : ''}`
        throw new HarnessError(`V-yovoice is busy: the compute scheduler refused admission (${status})${detail ? ': ' + detail : ''}. No complete transcript was saved; retry only when resources are available.`, 'AUDIO_SERVICE_BUSY', { cause })
      }
      if (cause.options.status === 413) {
        const status = `HTTP 413${cause.options.serviceCode ? `; ${cause.options.serviceCode}` : ''}`
        throw new HarnessError(`V-yovoice rejected the audio (${status})${detail ? ': ' + detail : ''}. Check file size, duration and part limits; no complete transcript was saved.`, 'AUDIO_TOO_LARGE', { cause })
      }
      if (cause.options.status !== undefined) {
        const status = `HTTP ${cause.options.status}${cause.options.serviceCode ? `; ${cause.options.serviceCode}` : ''}`
        throw new HarnessError(`V-yovoice request failed (${status})${detail ? ': ' + detail : ''}; no new transcript was saved. Check audio format and model limits.`, 'AUDIO_SERVICE_ERROR', { cause })
      }
      if (cause.code === 'response_too_large') {
        throw new HarnessError('V-yovoice response exceeds maxResponseBytes; no partial transcript was saved', 'AUDIO_RESPONSE_TOO_LARGE', { cause })
      }
      if (cause.code === 'invalid_response') {
        throw new HarnessError('V-yovoice returned invalid JSON; no transcript was saved.', 'AUDIO_INVALID_RESPONSE', { cause })
      }
      throw new HarnessError(cause.options.outcomeUnknown
        ? 'V-yovoice is unreachable or the request timed out. The remote execution outcome is unknown; no new transcript was saved. Report the error; do not retry automatically.'
        : 'V-yovoice is unreachable or the request timed out. No audio was submitted by this request. Report the connection error; do not retry automatically.', 'AUDIO_SERVICE_UNAVAILABLE', { cause })
    }
    throw cause
  }
}

/** Parse the remote model catalogue without accepting malformed wire data.
 * @param value - decoded model catalogue.
 * @returns ASR identities and calibrated inference readiness.
 */
export function modelRows(value: unknown): { key: string; name: string; ready: boolean }[] {
  if (!Array.isArray(value)) throw new HarnessError('V-yovoice returned an invalid model catalogue', 'AUDIO_INVALID_RESPONSE')
  return value.flatMap((row: unknown) => {
    if (typeof row !== 'object' || row === null || !('kind' in row) || row.kind !== 'asr') return []
    if (!('key' in row) || typeof row.key !== 'string' || !('name' in row) || typeof row.name !== 'string') {
      throw new HarnessError('V-yovoice returned an invalid ASR model', 'AUDIO_INVALID_RESPONSE')
    }
    return [{ key: row.key, name: row.name, ready: 'status' in row && row.status === 'ready' && 'inference_ready' in row && row.inference_ready === true }]
  })
}

/** Read required calibrated upload limits; inference is never attempted on unknown limits.
 * @param value - decoded model input limits.
 * @param configured - deployment upload cap.
 * @returns the smallest verified upload limit.
 */
export function uploadLimit(value: unknown, configured: number): number {
  if (typeof value !== 'object' || value === null || !('max_upload_bytes' in value) || typeof value.max_upload_bytes !== 'number'
    || !('limits' in value) || typeof value.limits !== 'object' || value.limits === null || !('input_bytes' in value.limits)
    || typeof value.limits.input_bytes !== 'number') throw new HarnessError('V-yovoice did not provide calibrated upload limits', 'AUDIO_INVALID_RESPONSE')
  const limit = Math.min(configured, value.max_upload_bytes, value.limits.input_bytes)
  if (!Number.isSafeInteger(limit) || limit < 1) throw new HarnessError('V-yovoice returned invalid upload limits', 'AUDIO_INVALID_RESPONSE')
  return limit
}

/** Discover the full-file API and its original-upload limit.
 * @param value - model input limits response.
 * @param configured - plugin upload cap.
 * @returns full-file upload limit, or undefined for an older service.
 */
export function fullUploadLimit(value: unknown, configured: number): number | undefined {
  if (typeof value !== 'object' || value === null) throw new HarnessError('Invalid model input limits', 'AUDIO_INVALID_RESPONSE')
  if (!('full_transcription' in value)) return undefined
  if (!('limits' in value) || typeof value.limits !== 'object' || value.limits === null
    || !('max_upload_bytes' in value) || typeof value.max_upload_bytes !== 'number'
    || !Number.isSafeInteger(value.max_upload_bytes) || value.max_upload_bytes < 1) {
    throw new HarnessError('V-yovoice did not provide calibrated full-file limits', 'AUDIO_INVALID_RESPONSE')
  }
  const full = value.full_transcription
  if (typeof full !== 'object' || full === null || !('endpoint' in full) || full.endpoint !== '/v1/audio/transcriptions/full'
    || !('max_upload_bytes' in full) || typeof full.max_upload_bytes !== 'number'
    || !Number.isSafeInteger(full.max_upload_bytes) || full.max_upload_bytes < 1
    || !('processing_version' in full) || typeof full.processing_version !== 'string' || !full.processing_version) {
    throw new HarnessError('V-yovoice returned invalid full-file capabilities', 'AUDIO_INVALID_RESPONSE')
  }
  return Math.min(configured, value.max_upload_bytes, full.max_upload_bytes)
}

/** Validate a complete full-file result and its cache identity.
 * @param value - decoded service response.
 * @param source - SHA-256 of the original uploaded bytes.
 * @param model - requested model.
 * @returns original text and service cache identity.
 */
export function fullTranscript(value: unknown, source: string, model: string): { text: string; cacheKey: string } {
  if (typeof value !== 'object' || value === null || !('complete' in value) || value.complete !== true
    || !('text' in value) || typeof value.text !== 'string' || !('model' in value) || value.model !== model
    || !('cache' in value) || typeof value.cache !== 'object' || value.cache === null
    || !('source_sha256' in value.cache) || value.cache.source_sha256 !== source
    || !('key' in value.cache) || typeof value.cache.key !== 'string' || !/^[a-f0-9]{64}$/u.test(value.cache.key)) {
    throw new HarnessError('V-yovoice did not return a complete, matching transcript', 'AUDIO_INVALID_RESPONSE')
  }
  return { text: value.text, cacheKey: value.cache.key }
}

/** Preserve the service's transcript verbatim, including an empty no-speech result.
 * @param value - decoded transcription response.
 * @returns exact recognized text.
 */
export function transcriptText(value: unknown): string {
  if (typeof value !== 'object' || value === null || !('text' in value) || typeof value.text !== 'string') {
    throw new HarnessError('V-yovoice returned an invalid transcript', 'AUDIO_INVALID_RESPONSE')
  }
  return value.text
}
