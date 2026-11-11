import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it, onTestFinished } from 'vitest'
import { audioPlaybackResponse, parseByteRange, serveNodeAudio } from '../src/playback.ts'

it('parses bounded, open, and suffix byte ranges and rejects malformed requests', () => {
  expect(parseByteRange(null, 10)).toBeUndefined()
  expect(parseByteRange('bytes=2-5', 10)).toEqual({ start: 2, end: 5 })
  expect(parseByteRange('bytes=7-', 10)).toEqual({ start: 7, end: 9 })
  expect(parseByteRange('bytes=-3', 10)).toEqual({ start: 7, end: 9 })
  expect(parseByteRange('bytes=10-', 10)).toBeNull()
  expect(parseByteRange('bytes=5-2', 10)).toBeNull()
  expect(parseByteRange('bytes=0-1,3-4', 10)).toBeNull()
})

it('streams only an attachment owned by the selected session and supports seeking', async () => {
  const root = await mkdtemp(join(tmpdir(), 'audio-playback-'))
  onTestFinished(() => rm(root, { recursive: true, force: true }))
  const path = join(root, 'meeting.mp3')
  await writeFile(path, Buffer.from('abcdefghij'))
  const attachmentId = `sha256:${'a'.repeat(64)}`
  const state = { files: [{ id: attachmentId, name: 'meeting.mp3', bytes: 10 }] }
  const session = { id: 'session-a' }
  const sessions = { get: (id: string) => id === 'session-a' ? session : undefined }
  const ctx = {
    get: () => sessions,
    projection: { stateOf: (target: unknown) => target === session ? state : undefined },
    attachments: { fileHostPath: () => path },
  }
  const request = (range?: string, method = 'GET') => new Request(
    `http://host/api/tool-audio-transcription/file?sessionId=session-a&attachmentId=${encodeURIComponent(attachmentId)}`,
    { method, headers: range === undefined ? {} : { Range: range } },
  )

  const ranged = await audioPlaybackResponse(ctx as never, request('bytes=2-5'), ctx.projection as never)
  expect(ranged.status).toBe(206)
  expect(ranged.headers.get('content-range')).toBe('bytes 2-5/10')
  expect(ranged.headers.get('content-type')).toBe('audio/mpeg')
  expect(await ranged.text()).toBe('cdef')

  const head = await audioPlaybackResponse(ctx as never, request('bytes=-3', 'HEAD'), ctx.projection as never)
  expect(head.status).toBe(206)
  expect(head.headers.get('content-length')).toBe('3')
  expect(await head.text()).toBe('')

  const wrongSession = await audioPlaybackResponse(ctx as never, new Request(
    `http://host/api/tool-audio-transcription/file?sessionId=session-b&attachmentId=${encodeURIComponent(attachmentId)}`,
  ), ctx.projection as never)
  expect(wrongSession.status).toBe(404)
})

it('rejects missing identities and unowned attachments', async () => {
  const sessions = { get: () => ({}) }
  const ctx = {
    get: () => sessions,
    projection: { stateOf: () => ({ files: [] }) },
    attachments: { fileHostPath: () => '/never-read' },
  }
  expect((await audioPlaybackResponse(ctx as never, new Request('http://host/api/tool-audio-transcription/file'), ctx.projection as never)).status).toBe(400)
  expect((await audioPlaybackResponse(ctx as never, new Request(
    'http://host/api/tool-audio-transcription/file?sessionId=s&attachmentId=outside',
  ), ctx.projection as never)).status).toBe(404)
})

it('bridges an authenticated exact Host route to the ranged audio response', async () => {
  const root = await mkdtemp(join(tmpdir(), 'audio-route-'))
  onTestFinished(() => rm(root, { recursive: true, force: true }))
  const path = join(root, 'meeting.wav')
  await writeFile(path, Buffer.from('abcdefghij'))
  const attachmentId = `sha256:${'c'.repeat(64)}`
  const session = { id: 'session-route' }
  const sessions = { get: () => session }
  const ctx = {
    get: () => sessions,
    connection: { requestRejection: () => undefined },
    projection: { stateOf: () => ({ files: [{ id: attachmentId, name: 'meeting.wav', bytes: 10 }] }) },
    attachments: { fileHostPath: () => path },
  }
  const output: Buffer[] = []
  const response = {
    writableEnded: false,
    status: 0,
    headers: {} as Record<string, string>,
    writeHead(status: number, headers: Record<string, string>) {
      this.status = status
      this.headers = headers
      return this
    },
    write(chunk: Uint8Array) {
      output.push(Buffer.from(chunk))
      return true
    },
    end() { this.writableEnded = true },
    on() { return this },
    once() { return this },
    off() { return this },
  }
  const request = {
    method: 'GET',
    url: `/api/tool-audio-transcription/file?sessionId=session-route&attachmentId=${encodeURIComponent(attachmentId)}`,
    headers: { host: 'dsh.test', range: 'bytes=3-5' },
  }
  await serveNodeAudio(ctx as never, request as never, response as never, new AbortController().signal, ctx.projection as never)
  expect(response.status).toBe(206)
  expect(response.headers['content-range']).toBe('bytes 3-5/10')
  expect(Buffer.concat(output).toString()).toBe('def')
})
