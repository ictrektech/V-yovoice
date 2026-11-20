/** Bounded JSON transport shared by V-yovoice capability adapters. */

/** Limits needed to issue one service request safely. */
export interface ServiceLimits {
  /** HTTP(S) service root without /v1. */
  baseUrl: string
  /** Complete request and response-read deadline. */
  requestTimeoutMs: number
  /** Maximum accepted response-body bytes. */
  maxResponseBytes: number
}

/** Transport failure that keeps HTTP and service semantics available to the feature layer. */
export class ServiceRequestError extends Error {
  /**
   * @param message - diagnostic text.
   * @param code - stable transport failure code.
   * @param options - HTTP status, service error code/detail and request outcome.
   */
  constructor(
    message: string,
    readonly code: 'unavailable' | 'response_too_large' | 'invalid_response' | 'http_error',
    readonly options: {
      status?: number
      serviceCode?: string
      detail?: string
      outcomeUnknown?: boolean
      cause?: unknown
    } = {},
  ) {
    super(message, { cause: options.cause })
  }
}

function parseServiceFailure(response: Response, text: string, outcomeUnknown: boolean): ServiceRequestError {
  let detail = ''
  let serviceCode = ''
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed && typeof parsed.detail === 'string') {
      detail = parsed.detail
    }
    if (typeof parsed === 'object' && parsed !== null && 'error' in parsed && typeof parsed.error === 'object' && parsed.error !== null
      && 'code' in parsed.error && typeof parsed.error.code === 'string' && /^[a-z0-9_]{1,100}$/u.test(parsed.error.code)) {
      serviceCode = parsed.error.code
    }
  } catch (error) {
    // The HTTP status remains authoritative when the service returns a non-JSON error page.
    void error
  }
  return new ServiceRequestError(`V-yovoice request failed (HTTP ${response.status})`, 'http_error', {
    status: response.status,
    serviceCode,
    detail,
    outcomeUnknown,
  })
}

function cancelReaderOnAbort(reader: ReadableStreamDefaultReader<Uint8Array>, signal: AbortSignal): void {
  void reader.cancel(signal.reason).catch((error: unknown) => {
    // The abort owns the outcome; an already closed transport may reject cancellation.
    void error
  })
}

function abortHandler(reader: ReadableStreamDefaultReader<Uint8Array>, signal: AbortSignal): () => void {
  return () => { cancelReaderOnAbort(reader, signal) }
}

async function readBoundedBody(response: Response, signal: AbortSignal, limit: number, outcomeUnknown: boolean): Promise<Buffer> {
  if (!response.body) {
    if (!response.ok) throw parseServiceFailure(response, '', outcomeUnknown)
    throw new ServiceRequestError('V-yovoice returned an empty response', 'invalid_response', { outcomeUnknown })
  }
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let bytes = 0
  const abortRead = abortHandler(reader, signal)
  signal.addEventListener('abort', abortRead, { once: true })
  try {
    while (true) {
      signal.throwIfAborted()
      const chunk = await reader.read()
      signal.throwIfAborted()
      if (chunk.done) break
      bytes += chunk.value.length
      if (bytes > limit) {
        throw new ServiceRequestError('V-yovoice response exceeds the configured limit', 'response_too_large', { outcomeUnknown })
      }
      chunks.push(chunk.value)
    }
  } finally {
    signal.removeEventListener('abort', abortRead)
    await reader.cancel()
    reader.releaseLock()
  }
  return Buffer.concat(chunks)
}

/** Read a bounded JSON response and preserve cancellation and upstream status. */
export async function requestServiceJson(
  config: ServiceLimits,
  path: string,
  signal: AbortSignal,
  body?: BodyInit,
  headers?: HeadersInit,
): Promise<unknown> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(config.requestTimeoutMs)])
  try {
    const response = await fetch(config.baseUrl + path, {
      method: body === undefined ? 'GET' : 'POST',
      ...(body === undefined ? {} : { body }),
      ...(headers === undefined ? {} : { headers }),
      signal: requestSignal,
      redirect: 'error',
    })
    const buffer = await readBoundedBody(response, requestSignal, config.maxResponseBytes, body !== undefined)
    const text = buffer.toString('utf8')
    if (!response.ok) {
      throw parseServiceFailure(response, text, body !== undefined)
    }
    try {
      return JSON.parse(text)
    } catch (cause) {
      throw new ServiceRequestError('V-yovoice returned invalid JSON', 'invalid_response', { cause, outcomeUnknown: body !== undefined })
    }
  } catch (cause) {
    signal.throwIfAborted()
    if (cause instanceof ServiceRequestError) throw cause
    throw new ServiceRequestError('V-yovoice is unreachable or the request timed out', 'unavailable', {
      cause,
      outcomeUnknown: body !== undefined,
    })
  }
}

/**
 * Stream one bounded WAV response while retaining HTTP and cancellation semantics.
 * @param config - service root, deadline and JSON error-body cap.
 * @param path - service-relative speech endpoint.
 * @param signal - tool and plugin cancellation.
 * @param payload - JSON request body.
 * @param maxBytes - maximum accepted audio bytes.
 * @returns ordered audio chunks suitable for durable attachment storage.
 */
export async function requestServiceAudio(
  config: ServiceLimits,
  path: string,
  signal: AbortSignal,
  payload: unknown,
  maxBytes: number,
): Promise<AsyncIterable<Uint8Array>> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(config.requestTimeoutMs)])
  try {
    const response = await fetch(config.baseUrl + path, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
      signal: requestSignal,
      redirect: 'error',
    })
    if (!response.ok) {
      const body = await readBoundedBody(response, requestSignal, config.maxResponseBytes, true)
      throw parseServiceFailure(response, body.toString('utf8'), true)
    }
    const contentType = response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase() ?? ''
    if (contentType !== 'audio/wav' && contentType !== 'audio/x-wav') {
      throw new ServiceRequestError('V-yovoice returned a non-WAV speech response', 'invalid_response', { outcomeUnknown: true })
    }
    if (!response.body) {
      throw new ServiceRequestError('V-yovoice returned an empty speech response', 'invalid_response', { outcomeUnknown: true })
    }
    const declared = Number(response.headers.get('content-length'))
    if (Number.isSafeInteger(declared) && declared > maxBytes) {
      throw new ServiceRequestError('V-yovoice speech response exceeds maxSpeechBytes', 'response_too_large', { outcomeUnknown: true })
    }
    return readAudioBody(response.body, requestSignal, maxBytes)
  } catch (cause) {
    signal.throwIfAborted()
    if (cause instanceof ServiceRequestError) throw cause
    throw new ServiceRequestError('V-yovoice is unreachable or the request timed out', 'unavailable', {
      cause,
      outcomeUnknown: true,
    })
  }
}

async function* readAudioBody(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  maxBytes: number,
): AsyncIterable<Uint8Array> {
  const reader = body.getReader()
  let bytes = 0
  const abortRead = abortHandler(reader, signal)
  signal.addEventListener('abort', abortRead, { once: true })
  try {
    while (true) {
      signal.throwIfAborted()
      const chunk = await reader.read()
      signal.throwIfAborted()
      if (chunk.done) break
      bytes += chunk.value.length
      if (bytes > maxBytes) {
        throw new ServiceRequestError('V-yovoice speech response exceeds maxSpeechBytes', 'response_too_large', { outcomeUnknown: true })
      }
      yield chunk.value
    }
  } finally {
    signal.removeEventListener('abort', abortRead)
    await reader.cancel()
    reader.releaseLock()
  }
}
