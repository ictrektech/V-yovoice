import { expect, it } from 'vitest'
import { speechArtifact, transcriptArtifact } from '../src/core/artifact.ts'
import { CapabilityRegistry } from '../src/core/capability.ts'
import { resolveConfig, resolveSpeechConfig } from '../src/core/config.ts'
import { completedOperation } from '../src/core/operation.ts'
import { speechModelRows } from '../src/features/speech/client.ts'

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
  expect(resolveSpeechConfig({ baseUrl: 'http://voice:7070', speechModel: 'kokoro', speechVoice: 'zf_xiaoxiao' })).toMatchObject({
    baseUrl: 'http://voice:7070', speechModel: 'kokoro', speechVoice: 'zf_xiaoxiao', maxSpeechBytes: 268_435_456,
  })
  expect(() => resolveSpeechConfig({ baseUrl: 'http://voice:7070', speechModel: 'kokoro' })).toThrow('default TTS voice')
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
  expect(speechArtifact({ source: 'b'.repeat(64), model: 'kokoro', voice: 'zf_xiaoxiao' })).toEqual({
    id: `speech:${'b'.repeat(64)}`,
    kind: 'audio',
    mimeType: 'audio/wav',
    source: 'b'.repeat(64),
    provenance: { capability: 'speech', model: 'kokoro', voice: 'zf_xiaoxiao' },
  })
  expect(speechModelRows([{
    kind: 'tts', key: 'kokoro', name: 'Kokoro', status: 'ready', capabilities: ['builtin_voices'],
    voices: { zf_xiaoxiao: { language: 'zh' } },
  }])).toEqual([{
    key: 'kokoro', name: 'Kokoro', ready: true, languages: [], capabilities: ['builtin_voices'],
    voices: [{ id: 'zf_xiaoxiao', name: 'zf_xiaoxiao', language: 'zh' }],
  }])
})
