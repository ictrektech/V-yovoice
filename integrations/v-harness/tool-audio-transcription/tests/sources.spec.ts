import { expect, it } from 'vitest'
import { missingTranscript, selectAudioFile } from '../src/sources.ts'

const first = { id: 'sha256:609ca12a11111111', name: 'voice.mp3', bytes: 10605 }
const second = { id: 'sha256:609ca12a22222222', name: 'other.mp3', bytes: 100 }

it('resolves the displayed digest only when unique within the authorized conversation', () => {
  expect(selectAudioFile([first], '609ca12a')).toEqual(first)
  expect(selectAudioFile([first], first.name)).toEqual(first)
  expect(selectAudioFile([first])).toEqual(first)
  expect(selectAudioFile([first, first])).toEqual(first)
  expect(() => selectAudioFile([first, second], '609ca12a')).toThrow('ambiguous')
  expect(() => selectAudioFile([first], '609')).toThrow('not found')
  expect(() => selectAudioFile([], first.id)).toThrow('not found')
  expect(() => selectAudioFile([first, second])).toThrow('ambiguous')
})

it('directs missing-transcript recovery to transcription rather than file permissions', () => {
  expect(missingTranscript([first])).toContain(JSON.stringify({ attachment_id: first.id }))
  expect(missingTranscript([first])).toContain('not a file permission error')
  expect(missingTranscript([first, second])).toContain('list_audio_files')
})
