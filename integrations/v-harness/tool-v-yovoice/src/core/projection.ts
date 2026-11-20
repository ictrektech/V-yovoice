/** Incremental session-owned audio sources, transcripts and generated speech, restored on resume. */
import { z } from 'zod'
import type { Context } from '@deepseek-ai/cordis'
import type { ToolRunContext } from '@deepseek-ai/dsh-tools'
import type { ProjectionHandle } from '@deepseek-ai/dsh-session-projection'
import type {} from '@deepseek-ai/dsh-tool-executor-ptc/types'
import { HarnessError } from '@deepseek-ai/dsh-llm'

const operationSchema = z.object({
  id: z.string(), capability: z.string(), state: z.enum(['queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out', 'unknown']),
  createdAt: z.string(), updatedAt: z.string(),
})
const artifactSchema = z.object({
  id: z.string(), kind: z.enum(['audio', 'transcript', 'score', 'midi', 'stems']), mimeType: z.string(),
  source: z.string(), provenance: z.object({ capability: z.string(), model: z.string().optional(), voice: z.string().optional() }),
})
const savedSchema = z.object({
  audioTranscript: z.literal(true), source: z.string(), model: z.string(),
  endpoint: z.string(), file: z.string(), text: z.string(), cacheKey: z.string().optional(),
  operation: operationSchema.optional(), artifact: artifactSchema.optional(),
})
const speechSchema = z.object({
  audioSpeech: z.literal(true), attachmentId: z.string(), file: z.string(), model: z.string(), voice: z.string(),
  text: z.string(), bytes: z.number(), language: z.string().optional(),
  operation: operationSchema.optional(), artifact: artifactSchema.optional(),
})
const stateSchema = z.object({
  files: z.array(z.object({ id: z.string(), name: z.string(), bytes: z.number() })),
  citations: z.array(z.string()), transcripts: z.array(savedSchema),
  speeches: z.array(speechSchema), pendingCalls: z.array(z.string()), pendingSpeechCalls: z.array(z.string()),
})
type AudioState = z.infer<typeof stateSchema>
export type AudioProjection = ProjectionHandle<AudioState>


/** Register the pure fold before sessions start accepting audio.
 * @param ctx - plugin scope owning registration and disposal.
 */
export async function registerAudioProjection(ctx: Context): Promise<AudioProjection> {
  return await ctx.sessionProjections.register({
    key: 'audioTranscription', stateVersion: 4, stateSchema,
    init: () => ({ files: [], citations: [], transcripts: [], speeches: [], pendingCalls: [], pendingSpeechCalls: [] }),
    apply(state, event) {
      if (event.type === 'user/message' && event.data.source.kind === 'user') {
        const content = event.data.content
        const blocks = typeof content === 'string' ? [{ type: 'text' as const, text: content }] : content
        const files = blocks.flatMap(block => block.type === 'file' ? [{ id: String(block.attachment.attachmentId), name: block.attachment.name, bytes: block.attachment.bytes }] : [])
        const citations = blocks.flatMap(block => block.type === 'text' ? [block.text] : [])
        return { ...state, files: [...state.files, ...files], citations: [...state.citations, ...citations] }
      }
      if (event.type === 'tool/call') {
        if (event.data.name === 'transcribe_audio') {
          return { ...state, pendingCalls: [...state.pendingCalls, event.data.callId] }
        }
        if (event.data.name === 'yovoice_speak') {
          return { ...state, pendingSpeechCalls: [...state.pendingSpeechCalls, event.data.callId] }
        }
        return state
      }
      if (event.type !== 'tool/result' && event.type !== 'tool/ptc-dispatch') return state
      if (event.type === 'tool/result') {
        const callId = event.data.message.toolCallId
        if (state.pendingSpeechCalls.includes(callId)) {
          const next = { ...state, pendingSpeechCalls: state.pendingSpeechCalls.filter(id => id !== callId) }
          if (event.data.message.isError) return next
          const speech = speechSchema.safeParse(event.data.meta)
          if (!speech.success) return next
          return { ...next, speeches: [...next.speeches.filter(item => item.attachmentId !== speech.data.attachmentId), speech.data] }
        }
        if (!state.pendingCalls.includes(callId)) return state
        state = { ...state, pendingCalls: state.pendingCalls.filter(id => id !== callId) }
        if (event.data.message.isError) return state
      } else if (event.data.name === 'yovoice_speak') {
        if (event.data.isError) return state
        const speech = speechSchema.safeParse(event.data.meta)
        if (!speech.success) return state
        return { ...state, speeches: [...state.speeches.filter(item => item.attachmentId !== speech.data.attachmentId), speech.data] }
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
 * @param projection - registered session projection.
 * @param exec - tool caller identity.
 * @returns the caller's restored audio state.
 */
export function audioState(projection: AudioProjection, exec: ToolRunContext): AudioState {
  if (!exec.agent) throw new HarnessError('Audio tools require a conversation', 'AUDIO_SESSION_REQUIRED')
  return audioStateOfSession(projection, exec.agent.session)
}

/** Read one session's durable audio projection without granting another session access.
 * @param projection - registered session projection.
 * @param session - exact loaded session.
 * @returns restored audio state when the projection is available.
 */
export function audioStateOfSession(projection: AudioProjection, session: Parameters<AudioProjection['stateOf']>[0]): AudioState {
  return projection.stateOf(session)
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
