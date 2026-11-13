import { expect, it } from 'vitest'
import { transcriptArtifact } from '../src/core/artifact.ts'
import { CapabilityRegistry } from '../src/core/capability.ts'
import { resolveConfig } from '../src/core/config.ts'
import { completedOperation } from '../src/core/operation.ts'

it('registers capabilities once in deterministic order', () => {
  const registry = new CapabilityRegistry()
  registry.register({ id: 'transcription', available: true })
  expect(registry.list()).toEqual([{ id: 'transcription', available: true }])
  expect(() => { registry.register({ id: 'transcription', available: true }) }).toThrow('already registered')
})

it('normalizes legacy settings and capability defaults to one service config', () => {
  expect(resolveConfig({
    baseUrl: 'http://voice:7070/',
    model: '',
    defaults: { transcription: { model: 'sensevoice' } },
  })).toMatchObject({
    baseUrl: 'http://voice:7070',
    model: 'sensevoice',
    requestTimeoutMs: 1_860_000,
    maxUploadBytes: 209_715_200,
  })
  expect(resolveConfig({ baseUrl: 'http://voice:7070', model: 'explicit' }, false).model).toBe('explicit')
  expect(() => resolveConfig({ baseUrl: 'http://voice:7070' })).toThrow('Select an ASR model')
})

it('describes transcript artifacts and completed synchronous work without storing text', () => {
  expect(transcriptArtifact({ source: 'a'.repeat(64), model: 'sensevoice', file: 'meeting.mp3' })).toEqual({
    id: `transcript:${'a'.repeat(64)}`,
    kind: 'transcript',
    mimeType: 'text/plain; charset=utf-8',
    source: 'a'.repeat(64),
    provenance: { capability: 'transcription', model: 'sensevoice' },
  })
  expect(completedOperation('transcription', `transcription:${'a'.repeat(64)}`)).toMatchObject({
    id: `transcription:${'a'.repeat(64)}`,
    capability: 'transcription',
    state: 'completed',
  })
})
