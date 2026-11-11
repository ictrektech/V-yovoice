/** Browser-safe identity of the plugin-owned audio stream route. */

/** Browser-relative route hosting one authenticated audio response. */
export const AUDIO_PLAYBACK_ROUTE = 'api/tool-audio-transcription/file'
/** Absolute registration path for the same response. */
export const AUDIO_PLAYBACK_PATH = `/${AUDIO_PLAYBACK_ROUTE}`

/** Browser-relative source URL for one authorized attachment.
 * @param sessionId - owning conversation.
 * @param attachmentId - exact uploaded attachment.
 * @returns relative route with encoded identities.
 */
export function audioPlaybackUrl(sessionId: string, attachmentId: string): string {
  const query = new URLSearchParams({ sessionId, attachmentId })
  return `${AUDIO_PLAYBACK_ROUTE}?${query}`
}
