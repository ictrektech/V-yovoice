/** Authenticated, session-scoped byte streaming for uploaded audio. */
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { extname } from 'node:path'
import { Readable } from 'node:stream'
import { brandString } from '@deepseek-ai/dsh-brand'
import type { AttachmentId } from '@deepseek-ai/dsh-attachment'
import type { Context } from '@deepseek-ai/cordis'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { audioStateOfSession } from './projection.ts'
import { AUDIO_PLAYBACK_PATH } from './playback-route.ts'

const BASE_HEADERS = {
  'Accept-Ranges': 'bytes',
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
}

const AUDIO_TYPES: Readonly<Record<string, string>> = {
  '.aac': 'audio/aac', '.flac': 'audio/flac', '.m4a': 'audio/mp4', '.mp3': 'audio/mpeg',
  '.oga': 'audio/ogg', '.ogg': 'audio/ogg', '.opus': 'audio/ogg', '.wav': 'audio/wav',
}

interface ByteRange { readonly start: number; readonly end: number }
function stringOr(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

/** Resolve one ranges request against an exact byte length.
 * @param header - HTTP Range header, or null for a complete response.
 * @param size - complete resource length.
 * @returns inclusive range, undefined for the complete resource, or null when unsatisfiable.
 */
export function parseByteRange(header: string | null, size: number): ByteRange | undefined | null {
  if (header === null) return undefined
  const match = /^bytes=(\d*)-(\d*)$/u.exec(header.trim())
  if (match === null || (match[1] === '' && match[2] === '')) return null
  if (match[1] === '') {
    const suffix = Number(match[2])
    if (!Number.isSafeInteger(suffix) || suffix <= 0 || size === 0) return null
    return { start: Math.max(0, size - suffix), end: size - 1 }
  }
  const start = Number(match[1])
  const requestedEnd = match[2] === '' ? size - 1 : Number(match[2])
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(requestedEnd) || start < 0 || start >= size || requestedEnd < start) return null
  return { start, end: Math.min(requestedEnd, size - 1) }
}

async function response(request: Request, sessionId: string, attachmentId: string, ctx: Context, lifetime: AbortSignal): Promise<Response> {
  const fail = (status: number, message: string): Response =>
    new Response(request.method === 'HEAD' ? null : message, { status, headers: BASE_HEADERS })
  const sessions = ctx.get('sessions')
  if (sessions === undefined) return fail(404, 'session store unavailable')
  const session = sessions.get(brandString<SessionId>(sessionId))
  if (session === undefined) return fail(404, 'session not found')
  const file = audioStateOfSession(ctx, session)?.files.find(candidate => candidate.id === attachmentId)
  if (file === undefined) return fail(404, 'audio attachment is not part of this session')
  const ref = { attachmentId: brandString<AttachmentId>(file.id), name: file.name, bytes: file.bytes }
  const path = ctx.attachments.fileHostPath(ref)
  if (path === undefined) return fail(409, 'audio playback is unavailable for this attachment provider')
  try {
    const info = await stat(path)
    if (!info.isFile()) return fail(403, 'audio source is not a regular file')
    const range = parseByteRange(request.headers.get('range'), info.size)
    if (range === null) return new Response(null, {
      status: 416,
      headers: { ...BASE_HEADERS, 'Content-Range': `bytes */${info.size}` },
    })
    const start = range?.start ?? 0
    const end = range?.end ?? info.size - 1
    const length = Math.max(0, end - start + 1)
    const headers = {
      ...BASE_HEADERS,
      'Content-Type': AUDIO_TYPES[extname(file.name).toLowerCase()] ?? 'application/octet-stream',
      'Content-Length': String(length),
      'Content-Disposition': `${new URL(request.url).searchParams.get('download') === '1' ? 'attachment' : 'inline'}; filename*=UTF-8''${encodeURIComponent(file.name)}`,
      ...(range === undefined ? {} : { 'Content-Range': `bytes ${start}-${end}/${info.size}` }),
    }
    if (request.method === 'HEAD') return new Response(null, { status: range === undefined ? 200 : 206, headers })
    const stream = createReadStream(path, { start, end })
    const combined = AbortSignal.any([request.signal, lifetime])
    if (combined.aborted) {
      stream.destroy()
      return fail(499, 'audio request cancelled')
    }
    const cleanup = (): void => { stream.destroy() }
    combined.addEventListener('abort', cleanup, { once: true })
    stream.once('close', () => { combined.removeEventListener('abort', cleanup) })
    return new Response(Readable.toWeb(stream) as ReadableStream<Uint8Array>, {
      status: range === undefined ? 200 : 206,
      headers,
    })
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return fail(404, 'audio source not found')
    throw error
  }
}

/** Serve an uploaded audio file only when it belongs to the named loaded session.
 * @param ctx - attachment, session and projection services.
 * @param request - authenticated GET or HEAD request.
 * @param lifetime - plugin unload cancellation for active streams.
 * @returns streamed audio with byte-range support.
 */
export async function audioPlaybackResponse(ctx: Context, request: Request, lifetime = new AbortController().signal): Promise<Response> {
  const url = new URL(request.url)
  const sessionId = url.searchParams.get('sessionId')
  const attachmentId = url.searchParams.get('attachmentId')
  if (sessionId === null || sessionId === '' || attachmentId === null || attachmentId === '') {
    return new Response('sessionId and attachmentId are required', { status: 400, headers: BASE_HEADERS })
  }
  return response(request, sessionId, attachmentId, ctx, lifetime)
}

/** Adapt the authenticated Fetch response to an exact Host HTTP route.
 * @param ctx - connection and audio playback services.
 * @param req - incoming GET or HEAD request.
 * @param res - response owned to completion.
 * @param lifetime - plugin unload cancellation for active streams.
 */
export async function serveNodeAudio(ctx: Context, req: IncomingMessage, res: ServerResponse, lifetime: AbortSignal): Promise<void> {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' })
    res.end()
    return
  }
  const rejection = ctx.connection.requestRejection(req)
  if (rejection !== undefined) {
    res.writeHead(rejection, { 'Cache-Control': 'private, no-store' })
    res.end(rejection === 401 ? 'unauthorized' : 'forbidden')
    return
  }
  const abort = new AbortController()
  res.on('close', () => {
    if (!res.writableEnded) abort.abort()
  })
  const requestUrl = stringOr(req.url, AUDIO_PLAYBACK_PATH)
  const requestHost = stringOr(req.headers.host, 'dsh.invalid')
  const url = new URL(requestUrl, `http://${requestHost}`)
  const headers = new Headers()
  for (const [name, value] of Object.entries(req.headers)) {
    if (typeof value === 'string') headers.set(name, value)
    else if (Array.isArray(value)) headers.set(name, value.join(', '))
  }
  const responseValue = await audioPlaybackResponse(ctx, new Request(url, {
    method: req.method,
    headers,
    signal: AbortSignal.any([abort.signal, lifetime]),
  }), lifetime)
  res.writeHead(responseValue.status, Object.fromEntries(responseValue.headers))
  if (responseValue.body === null) {
    res.end()
    return
  }
  for await (const chunk of responseValue.body) {
    if (abort.signal.aborted) continue
    if (!res.write(chunk)) {
      await new Promise<void>((resolve) => {
        const done = (): void => {
          res.off('drain', done)
          res.off('close', done)
          resolve()
        }
        res.once('drain', done)
        res.once('close', done)
      })
    }
  }
  res.end()
}
