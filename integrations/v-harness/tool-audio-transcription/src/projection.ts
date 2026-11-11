/** Incremental session-owned audio sources and verbatim transcript results, restored on resume. */
import { z } from 'zod'
import type { Context } from '@deepseek-ai/cordis'
import type { ToolRunContext } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-session-projection'
import { HarnessError } from '@deepseek-ai/dsh-llm'

const savedSchema = z.object({
  audioTranscript: z.literal(true), source: z.string(), model: z.string(),
  endpoint: z.string(), file: z.string(), text: z.string(), cacheKey: z.string().optional(),
})
const stateSchema = z.object({
  files: z.array(z.object({ id: z.string(), name: z.string(), bytes: z.number() })),
  citations: z.array(z.string()), transcripts: z.array(savedSchema),
  pendingCalls: z.array(z.string()),
})
type AudioState = z.infer<typeof stateSchema>
declare module '@deepseek-ai/dsh-session-projection/types' {
  interface SessionProjectionStateMap {
    /** Audio sources and original transcripts owned by this session. */
    audioTranscription: AudioState
  }
}

/** Register the pure fold before sessions start accepting audio.
 * @param ctx - plugin scope owning registration and disposal.
 */
export function registerAudioProjection(ctx: Context): void {
  ctx.sessionProjections.register({
    key: 'audioTranscription', stateVersion: 2, stateSchema,
    init: () => ({ files: [], citations: [], transcripts: [], pendingCalls: [] }),
    apply(state, event) {
      if (event.type === 'user/message' && event.data.source.kind === 'user') {
        const content = event.data.content
        const blocks = typeof content === 'string' ? [{ type: 'text' as const, text: content }] : content
        const files = blocks.flatMap(block => block.type === 'file' ? [{ id: String(block.attachment.attachmentId), name: block.attachment.name, bytes: block.attachment.bytes }] : [])
        const citations = blocks.flatMap(block => block.type === 'text' ? [block.text] : [])
        return { ...state, files: [...state.files, ...files], citations: [...state.citations, ...citations] }
      }
      if (event.type === 'tool/call' && event.data.name === 'transcribe_audio') {
        return { ...state, pendingCalls: [...state.pendingCalls, event.data.callId] }
      }
      if (event.type !== 'tool/result' && event.type !== 'tool/ptc-dispatch') return state
      if (event.type === 'tool/result') {
        if (!state.pendingCalls.includes(event.data.message.toolCallId)) return state
        state = { ...state, pendingCalls: state.pendingCalls.filter(id => id !== event.data.message.toolCallId) }
        if (event.data.message.isError) return state
      } else if (event.data.name !== 'transcribe_audio' || event.data.isError) return state
      const parsed = savedSchema.safeParse(event.data.meta)
      if (!parsed.success) return state
      const saved = parsed.data
      return { ...state, transcripts: [...state.transcripts.filter(item =>
        item.source !== saved.source || item.model !== saved.model || item.endpoint !== saved.endpoint), saved] }
    },
  })
}

/** Read the maintained state of the calling conversation; other sessions are inaccessible.
 * @param ctx - scope providing session projections.
 * @param exec - tool caller identity.
 * @returns the caller's restored audio state.
 */
export function audioState(ctx: Context, exec: ToolRunContext): AudioState {
  if (!exec.agent) throw new HarnessError('Audio tools require a conversation', 'AUDIO_SESSION_REQUIRED')
  const state = audioStateOfSession(ctx, exec.agent.session)
  if (!state) throw new HarnessError('Audio projection is unavailable', 'AUDIO_STATE_UNAVAILABLE')
  return state
}

/** Read one session's durable audio projection without granting another session access.
 * @param ctx - scope providing Session projections.
 * @param session - exact loaded session.
 * @returns restored audio state when the projection is available.
 */
export function audioStateOfSession(ctx: Context, session: Parameters<Context['sessionProjections']['stateOf']>[0]): AudioState | undefined {
  return ctx.sessionProjections.stateOf(session, 'audioTranscription')
}

/** Accept exact whitespace-delimited, quoted or @-mentioned paths supplied in user messages.
 * @param text - text committed by the user.
 * @param path - requested execution-world path.
 * @returns whether the exact path was cited.
 */
export function citesPath(text: string, path: string): boolean {
  const escaped = path.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')
  return new RegExp(`(?:^|[\\s"'\\x60(@（])${escaped}(?=$|[\\s"'\\x60)），。；！？])`, 'u').test(text)
}
