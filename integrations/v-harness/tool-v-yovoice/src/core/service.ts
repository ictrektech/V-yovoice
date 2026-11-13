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

/** Read a bounded JSON response and preserve cancellation and upstream status. */
export async function requestServiceJson(
  config: ServiceLimits,
  path: string,
  signal: AbortSignal,
  body?: FormData,
): Promise<unknown> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(config.requestTimeoutMs)])
  try {
    const response = await fetch(config.baseUrl + path, {
      method: body === undefined ? 'GET' : 'POST',
      ...(body === undefined ? {} : { body }),
      signal: requestSignal,
      redirect: 'error',
    })
    if (!response.body) {
      if (!response.ok) {
        throw new ServiceRequestError(`V-yovoice request failed (HTTP ${response.status})`, 'http_error', {
          status: response.status,
          outcomeUnknown: body !== undefined,
        })
      }
      throw new ServiceRequestError('V-yovoice returned an empty response', 'invalid_response')
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
        if (bytes > config.maxResponseBytes) {
          throw new ServiceRequestError('V-yovoice response exceeds maxResponseBytes', 'response_too_large', {
            outcomeUnknown: body !== undefined,
          })
        }
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
      throw new ServiceRequestError(`V-yovoice request failed (HTTP ${response.status})`, 'http_error', {
        status: response.status,
        serviceCode,
        detail,
        outcomeUnknown: body !== undefined,
      })
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
