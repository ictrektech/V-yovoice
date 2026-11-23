/** Canonical browser dictation WAV validation before service admission. */
import { HarnessError } from '@deepseek-ai/dsh-llm'

const SAMPLE_RATE = 16_000
const BYTES_PER_SECOND = SAMPLE_RATE * 2

function fourCC(bytes: Uint8Array, offset: number): string {
  return String.fromCharCode(bytes[offset] ?? 0, bytes[offset + 1] ?? 0, bytes[offset + 2] ?? 0, bytes[offset + 3] ?? 0)
}

function invalid(message: string): never {
  throw new HarnessError(message, 'AUDIO_INVALID_SOURCE')
}

/**
 * Validate the single WAV encoding produced by the dictation control.
 * @param bytes - complete RIFF/WAVE recording.
 * @param maxDurationSeconds - profile-owned recording bound.
 * @returns validated duration in seconds.
 */
export function validateDictationWave(bytes: Uint8Array, maxDurationSeconds: number): number {
  if (bytes.byteLength < 44) invalid('Dictation audio is not a complete WAV recording.')
  if (fourCC(bytes, 0) !== 'RIFF' || fourCC(bytes, 8) !== 'WAVE') invalid('Dictation audio must be a RIFF/WAVE recording.')
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const declaredBytes = view.getUint32(4, true) + 8
  if (declaredBytes !== bytes.byteLength) invalid('Dictation WAV length is inconsistent.')

  let format: { channels: number; sampleRate: number; byteRate: number; blockAlign: number; bits: number } | undefined
  let dataBytes: number | undefined
  let offset = 12
  while (offset + 8 <= bytes.byteLength) {
    const id = fourCC(bytes, offset)
    const size = view.getUint32(offset + 4, true)
    const body = offset + 8
    const end = body + size
    if (end > bytes.byteLength) invalid('Dictation WAV contains an incomplete chunk.')
    if (id === 'fmt ') {
      if (format !== undefined || size < 16) invalid('Dictation WAV has an invalid format chunk.')
      format = {
        channels: view.getUint16(body + 2, true),
        sampleRate: view.getUint32(body + 4, true),
        byteRate: view.getUint32(body + 8, true),
        blockAlign: view.getUint16(body + 12, true),
        bits: view.getUint16(body + 14, true),
      }
      if (view.getUint16(body, true) !== 1) invalid('Dictation audio must use uncompressed PCM.')
    } else if (id === 'data') {
      if (dataBytes !== undefined) invalid('Dictation WAV contains more than one data chunk.')
      dataBytes = size
    }
    offset = end + (size % 2)
  }

  if (format === undefined || dataBytes === undefined) invalid('Dictation WAV is missing audio data.')
  if (format.channels !== 1 || format.sampleRate !== SAMPLE_RATE || format.byteRate !== BYTES_PER_SECOND
    || format.blockAlign !== 2 || format.bits !== 16) {
    invalid('Dictation audio must be 16 kHz mono PCM16.')
  }
  if (dataBytes === 0 || dataBytes % 2 !== 0) invalid('Dictation recording is empty.')
  const durationSeconds = dataBytes / BYTES_PER_SECOND
  if (durationSeconds > maxDurationSeconds) {
    invalid(`Dictation recording exceeds the ${maxDurationSeconds}-second limit.`)
  }
  return durationSeconds
}
