import { expect, it } from 'vitest'
import { audioBase64, encodeWave } from '../src/client/recording.ts'

it('encodes mono 16 kHz PCM16 WAV and transfers it as canonical base64', () => {
  const samples = new Float32Array([0, -1, 1, 0.5])
  const bytes = encodeWave(samples)
  const view = new DataView(bytes.buffer)
  expect(new TextDecoder().decode(bytes.subarray(0, 4))).toBe('RIFF')
  expect(new TextDecoder().decode(bytes.subarray(8, 12))).toBe('WAVE')
  expect(view.getUint16(22, true)).toBe(1)
  expect(view.getUint32(24, true)).toBe(16_000)
  expect(view.getUint32(40, true)).toBe(samples.length * 2)
  expect(view.getInt16(44, true)).toBe(0)
  expect(view.getInt16(46, true)).toBe(-32_768)
  expect(view.getInt16(48, true)).toBe(32_767)
  expect(view.getInt16(50, true)).toBe(16_384)
  expect(Buffer.from(audioBase64(bytes), 'base64')).toEqual(Buffer.from(bytes))
})
