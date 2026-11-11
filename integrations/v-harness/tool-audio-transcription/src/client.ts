/** V-yovoice HTTP transport; audio decoding and calibrated limits remain service-owned. */
import { HarnessError } from '@deepseek-ai/dsh-llm'

/** Resolved endpoint and resource bounds shared by the HTTP requests. */
export interface VoiceConfig {
  /** HTTP(S) service root without /v1. */
  baseUrl: string
  /** Administrator-selected ASR model key. */
  model: string
  /** Maximum time in milliseconds for each request. */
  requestTimeoutMs: number
  /** Deployment cap on acquired audio bytes. */
  maxUploadBytes: number
  /** Maximum UTF-16 characters in a model-visible window. */
  pageCharacters: number
  /** Maximum bytes in a complete service JSON response. */
  maxResponseBytes: number
}

/** Validate deployment settings before advertising the tools.
 * @param config - explicit service and model plus optional deployment bounds.
 * @param requireModel - require a selected model for inference; catalogue lookup needs only the endpoint.
 * @returns the validated settings with defaults resolved.
 */
export function resolveConfig(config: Partial<VoiceConfig>, requireModel = true): VoiceConfig {
  if (!config.baseUrl?.trim()) throw new HarnessError('Configure the V-yovoice service address and ASR model in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  let baseUrl: URL
  try { baseUrl = new URL(config.baseUrl) } catch (cause) { throw new HarnessError('V-yovoice service address must be an HTTP(S) URL.', 'AUDIO_INVALID_CONFIG', { cause }) }
  if (!['http:', 'https:'].includes(baseUrl.protocol) || baseUrl.username || baseUrl.password || baseUrl.search || baseUrl.hash) {
    throw new Error('audio-transcription: baseUrl must be an HTTP(S) service root without credentials, query or fragment')
  }
  if (requireModel && !config.model?.trim()) throw new HarnessError('Select an ASR model in the plugin page.', 'AUDIO_NOT_CONFIGURED')
  const resolved = {
    baseUrl: baseUrl.href.replace(/\/+$/u, ''), model: config.model ?? '',
    requestTimeoutMs: config.requestTimeoutMs ?? 1_860_000,
    maxUploadBytes: config.maxUploadBytes ?? 200 * 1024 * 1024,
    pageCharacters: config.pageCharacters ?? 12_000,
    maxResponseBytes: config.maxResponseBytes ?? 16 * 1024 * 1024,
  }
  for (const [key, value] of Object.entries(resolved)) {
    if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 1 || value > 2_147_483_647)) {
      throw new Error(`audio-transcription: ${key} must be a positive integer within timer/buffer limits`)
    }
  }
  return resolved
}

/** Fetch a bounded JSON response, propagate cancellation and reject HTTP errors.
 * @param config - validated deployment settings.
 * @param path - service-relative endpoint.
 * @param signal - caller cancellation.
 * @param body - multipart upload for POST; omitted for GET.
 * @returns decoded wire data for operation-specific validation.
 */
export async function voiceJson(config: VoiceConfig, path: string, signal: AbortSignal, body?: FormData): Promise<unknown> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(config.requestTimeoutMs)])
  try {
    const response = await fetch(config.baseUrl + path, {
      method: body === undefined ? 'GET' : 'POST', ...body === undefined ? {} : { body },
      signal: requestSignal, redirect: 'error',
    })
    if (!response.body) {
      if (response.status === 429) throw new HarnessError('V-yovoice is busy (HTTP 429); no complete transcript was saved.', 'AUDIO_SERVICE_BUSY')
      if (response.status === 413) throw new HarnessError('V-yovoice rejected audio limits (HTTP 413); no complete transcript was saved.', 'AUDIO_TOO_LARGE')
      if (!response.ok) throw new HarnessError(`V-yovoice request failed (HTTP ${response.status}); no new transcript was saved.`, 'AUDIO_SERVICE_ERROR')
      throw new HarnessError('V-yovoice returned an empty response', 'AUDIO_INVALID_RESPONSE')
    }
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let bytes = 0
    const abortRead = () => {
      void reader.cancel(requestSignal.reason).catch((error: unknown) => {
        // The abort owns the outcome; an already closed transport may reject cancellation.
        void error
      })
    }
    requestSignal.addEventListener('abort', abortRead, { once: true })
    try {
      while (true) {
        requestSignal.throwIfAborted()
        const chunk = await reader.read()
        requestSignal.throwIfAborted()
        if (chunk.done) break
        bytes += chunk.value.length
        if (bytes > config.maxResponseBytes) throw new HarnessError('V-yovoice response exceeds maxResponseBytes; no partial transcript was saved', 'AUDIO_RESPONSE_TOO_LARGE')
        chunks.push(chunk.value)
      }
    } finally {
      requestSignal.removeEventListener('abort', abortRead)
      await reader.cancel()
      reader.releaseLock()
    }
    const text = Buffer.concat(chunks).toString('utf8')
    if (!response.ok) {
      let detail = ''
      let code = ''
      try {
        const body: unknown = JSON.parse(text)
        if (typeof body === 'object' && body !== null && 'detail' in body && typeof body.detail === 'string') {
          detail = body.detail.length > config.pageCharacters
            ? body.detail.slice(0, config.pageCharacters) + '… (service error detail shortened)' : body.detail
        }
        if (typeof body === 'object' && body !== null && 'error' in body && typeof body.error === 'object' && body.error !== null
          && 'code' in body.error && typeof body.error.code === 'string' && /^[a-z0-9_]{1,100}$/u.test(body.error.code)) code = body.error.code
      } catch (error) {
        // The HTTP status remains authoritative when the service returns a non-JSON error page.
        void error
      }
      const status = `HTTP ${response.status}${code ? `; ${code}` : ''}`
      if (response.status === 429) throw new HarnessError(`V-yovoice is busy: the compute scheduler refused admission (${status})${detail ? ': ' + detail : ''}. No complete transcript was saved; retry only when resources are available.`, 'AUDIO_SERVICE_BUSY')
      if (response.status === 413) throw new HarnessError(`V-yovoice rejected the audio (${status})${detail ? ': ' + detail : ''}. Check file size, duration and part limits; no complete transcript was saved.`, 'AUDIO_TOO_LARGE')
      throw new HarnessError(`V-yovoice request failed (${status})${detail ? ': ' + detail : ''}; no new transcript was saved. Check audio format and model limits.`, 'AUDIO_SERVICE_ERROR')
    }
    try { return JSON.parse(text) }
    catch (cause) { throw new HarnessError('V-yovoice returned invalid JSON; no transcript was saved.', 'AUDIO_INVALID_RESPONSE', { cause }) }
  } catch (cause) {
    signal.throwIfAborted()
    if (cause instanceof HarnessError) throw cause
    throw new HarnessError(body === undefined
      ? 'V-yovoice is unreachable or the request timed out. No audio was submitted by this request. Report the connection error; do not retry automatically.'
      : 'V-yovoice is unreachable or the request timed out. The remote execution outcome is unknown; no new transcript was saved. Report the error; do not retry automatically.', 'AUDIO_SERVICE_UNAVAILABLE', { cause })
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
