/** Project speech synthesis calls and durable results outside the collapsed tool process. */
import { isAppendSurfaceEvent } from '@deepseek-ai/dsh-session/surface'
import type { ConversationNodeDefinition } from '@deepseek-ai/dsh-client-ui-conversation/client'

/** One speech call rendered in the current turn. */
export interface SpeechTurnItem {
  readonly callId: string
  readonly seq: number
  readonly state: 'running' | 'success' | 'error'
  readonly text: string
  readonly attachmentId?: string
  readonly file?: string
  readonly model?: string
  readonly voice?: string
  readonly bytes?: number
  readonly error?: string
}

/** Speech cards produced within one turn. */
export interface SpeechTurnData { readonly items: readonly SpeechTurnItem[] }

declare module '@deepseek-ai/dsh-client-ui-conversation/client' {
  interface ConversationTurnDataMap {
    /** Speech synthesis states settled in this turn. */
    'audio-speech': SpeechTurnData
  }
}

interface SpeechCall {
  readonly callId: string
  readonly text: string
  readonly voice?: string
}

interface SpeechTurnState {
  readonly turn: number
  readonly calls: ReadonlyMap<string, SpeechCall>
  readonly items: readonly SpeechTurnItem[]
}

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : undefined
}

function contentText(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return (content as readonly unknown[]).flatMap((part) => {
    const value = record(part)
    return value?.['type'] === 'text' && typeof value['text'] === 'string' ? [value['text']] : []
  }).join('\n')
}

function callRecord(callId: string, argsRaw: string): SpeechCall {
  let args: Record<string, unknown> = {}
  try {
    const parsed: unknown = JSON.parse(argsRaw)
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) args = parsed as Record<string, unknown>
  } catch {
    // A malformed call remains visible; the tool itself returns the validation failure.
  }
  return {
    callId,
    text: typeof args.text === 'string' ? args.text : '',
    ...(typeof args.voice === 'string' ? { voice: args.voice } : {}),
  }
}

/** Rebuild turn-local speech cards from durable calls and results. */
export const speechTurnDefinition: ConversationNodeDefinition<SpeechTurnState> = {
  kind: 'audio-speech',
  match: (event) => {
    if (event.type === 'turn/start') return { id: String(event.data.turn), role: 'start' }
    if (event.type === 'tool/call' && event.data.name === 'yovoice_speak') {
      return { id: String(event.data.turn), role: 'update' }
    }
    if (event.type === 'tool/result' && isAppendSurfaceEvent(event)) return { id: String(event.data.turn), role: 'update' }
    return null
  },
  start: (_context, match) => {
    if (match.event.type !== 'turn/start') throw new Error('audio-speech start requires turn/start')
    return { turn: match.event.data.turn, calls: new Map(), items: [] }
  },
  update: (context, match) => {
    const event = match.event
    if (event.type === 'tool/call') {
      if (event.data.name !== 'yovoice_speak') return context.state
      const callId = String(event.data.callId)
      const call = callRecord(callId, event.data.arguments)
      const calls = new Map(context.state.calls)
      calls.set(callId, call)
      const running: SpeechTurnItem = {
        callId, seq: event.seq, state: 'running', text: call.text,
        ...(call.voice === undefined ? {} : { voice: call.voice }),
      }
      return { ...context.state, calls, items: [...context.state.items, running] }
    }
    if (event.type !== 'tool/result') return context.state
    const callId = String(event.data.message.source.callId)
    const call = context.state.calls.get(callId)
    if (call === undefined) return context.state
    const remainingCalls = new Map(context.state.calls)
    remainingCalls.delete(callId)
    let item: SpeechTurnItem
    if (event.data.message.isError === true) {
      item = {
        callId, seq: event.seq, state: 'error', text: call.text,
        ...(call.voice === undefined ? {} : { voice: call.voice }),
        error: contentText(event.data.message.content),
      }
    } else {
      const meta = event.data.meta
      if (typeof meta !== 'object' || meta === null || !('audioSpeech' in meta) || meta.audioSpeech !== true
        || !('attachmentId' in meta) || typeof meta.attachmentId !== 'string'
        || !('file' in meta) || typeof meta.file !== 'string'
        || !('model' in meta) || typeof meta.model !== 'string'
        || !('voice' in meta) || typeof meta.voice !== 'string'
        || !('text' in meta) || typeof meta.text !== 'string'
        || !('bytes' in meta) || typeof meta.bytes !== 'number') return { ...context.state, calls: remainingCalls }
      item = {
        callId, seq: event.seq, state: 'success', text: meta.text,
        attachmentId: meta.attachmentId, file: meta.file, model: meta.model,
        voice: meta.voice, bytes: meta.bytes,
      }
    }
    return {
      ...context.state,
      calls: remainingCalls,
      items: context.state.items.map(existing => existing.callId === callId ? item : existing),
    }
  },
  buildLocationData: (context, scope, previous) => {
    if (scope !== 'turn' || context.state === undefined) return null
    if (previous?.kind === 'turn' && previous.turn === context.state.turn
      && previous.key === 'audio-speech' && previous.value.items === context.state.items) return previous
    return { kind: 'turn', turn: context.state.turn, key: 'audio-speech', value: { items: context.state.items } }
  },
}
