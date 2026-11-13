/** Resolve model-visible selectors only within the caller's authorized file inventory. */
import { HarnessError } from '@deepseek-ai/dsh-llm'

interface AudioFile { id: string; name: string; bytes: number }

/**
 * Select one authorized file using its exact ID, name, or unambiguous displayed digest prefix.
 * @param files - files admitted to this conversation.
 * @param selector - model selector; omission is allowed only for one file.
 * @returns the single matching authorized file.
 */
export function selectAudioFile(files: readonly AudioFile[], selector?: string): AudioFile {
  const matches = selector === undefined ? files : files.filter(file => file.id === selector || file.name === selector
    || (selector.length >= 8 && (file.id.startsWith(selector) || file.id.startsWith(`sha256:${selector}`))))
  const unique = [...new Map(matches.map(file => [file.id, file])).values()]
  const selected = unique[0]
  if (unique.length === 1 && selected !== undefined) return selected
  const choices = files.map(file => ({ name: file.name, attachment_id: file.id }))
  throw new HarnessError(
    `Audio source ${unique.length > 1 ? 'is ambiguous' : 'was not found in this conversation'}. `
    + 'For an uploaded file, use list_audio_files and call transcribe_audio with one exact attachment_id from its result. '
    + 'For a path explicitly written by the user, use file_path instead. '
    + `Do not use shell commands, read, or request wider file permissions. Available files: ${JSON.stringify(choices)}`,
    'AUDIO_INVALID_SOURCE',
  )
}

/**
 * Explain how to create a missing transcript without misreporting a permission failure.
 * @param files - current conversation's authorized files.
 * @returns actionable tool-call guidance.
 */
export function missingTranscript(files: readonly AudioFile[]): string {
  const args = files.length === 1 ? { attachment_id: files[0]?.id } : null
  return 'No saved transcript matches this reference. This is not a file permission error. '
    + (args === null ? 'Call list_audio_files, then transcribe_audio with an attachment_id from that result. '
      : `First call transcribe_audio with ${JSON.stringify(args)}. `)
    + 'Use read_audio_transcript only after successful transcription. Never use read, bash, sudo, or wider permissions to decode speech.'
}
