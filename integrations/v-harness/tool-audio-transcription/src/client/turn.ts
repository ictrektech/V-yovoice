/** Project audio calls and durable results outside the collapsed tool process. */
import { isAppendSurfaceEvent } from '@deepseek-ai/dsh-session/surface'
import type { ConversationNodeDefinition } from '@deepseek-ai/dsh-client-ui-conversation/client'

/** One rendered state for an audio call in the current turn. */
export interface AudioTurnItem {
  readonly callId: string
  readonly seq: number
  readonly state: 'running' | 'success' | 'error'
  readonly file: string
  readonly attachmentId?: string
  readonly source?: string
  readonly model?: string
  readonly text?: string
  readonly error?: string
}

/** Audio cards produced within one turn. */
export interface AudioTurnData { readonly items: readonly AudioTurnItem[] }

declare module '@deepseek-ai/dsh-client-ui-conversation/client' {
  interface ConversationTurnDataMap {
    /** Audio call states settled in this turn. */
    'audio-originals': AudioTurnData
  }
}

interface AudioCall {
  readonly callId: string
  readonly file: string
  readonly transcribe: boolean
  readonly attachmentId?: string
  readonly filePath?: boolean
}

interface AudioTurnState {
  readonly turn: number
  readonly files: readonly { readonly id: string; readonly name: string; readonly bytes: number }[]
  readonly calls: ReadonlyMap<string, AudioCall>
  readonly items: readonly AudioTurnItem[]
}

function basename(path: string): string {
  return path.split(/[\\/]/u).at(-1) || path
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

function selectedFile(files: AudioTurnState['files'], selector: string | undefined): AudioTurnState['files'][number] | undefined {
  const matches = selector === undefined ? files : files.filter(file => file.id === selector || file.name === selector
    || (selector.length >= 8 && (file.id.startsWith(selector) || file.id.startsWith(`sha256:${selector}`))))
  const unique = [...new Map(matches.map(file => [file.id, file])).values()]
  return unique.length === 1 ? unique[0] : undefined
}

function callRecord(files: AudioTurnState['files'], callId: string, name: string, argsRaw: string): AudioCall {
  let args: Record<string, unknown> = {}
  try {
    const parsed: unknown = JSON.parse(argsRaw)
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) args = parsed as Record<string, unknown>
  } catch {
    // A malformed call remains visible; the tool itself returns the validation failure.
  }
  const selector = typeof args.attachment_id === 'string' ? args.attachment_id : undefined
  const filePath = typeof args.file_path === 'string' ? args.file_path : undefined
  const selected = selectedFile(files, selector)
  return {
    callId,
    file: selected?.name ?? (filePath === undefined ? selector ?? '' : basename(filePath)),
    transcribe: name === 'transcribe_audio',
    ...(selected === undefined ? {} : { attachmentId: selected.id }),
    ...(filePath === undefined ? {} : { filePath: true }),
  }
}

function resultText(content: unknown): string {
  return contentText(content)
}

function inventory(text: string): AudioTurnState['files'] {
  try {
    const parsed: unknown = JSON.parse(text)
    if (!Array.isArray(parsed)) return []
    return (parsed as readonly unknown[]).flatMap((item) => {
      const value = record(item)
      return typeof value?.['attachment_id'] === 'string'
        && typeof value['name'] === 'string' && typeof value['bytes'] === 'number'
        ? [{ id: value['attachment_id'], name: value['name'], bytes: value['bytes'] }] : []
    })
  } catch {
    return []
  }
}

/** Rebuild turn-local cards from durable calls and results. */
export const audioTurnDefinition: ConversationNodeDefinition<AudioTurnState> = {
  kind: 'audio-originals',
  match: (event) => {
    if (event.type === 'turn/start') return { id: String(event.data.turn), role: 'start' }
    if (event.type === 'tool/call' && (event.data.name === 'transcribe_audio' || event.data.name === 'list_audio_files')) {
      return { id: String(event.data.turn), role: 'update' }
    }
    if (event.type === 'tool/result' && isAppendSurfaceEvent(event)) return { id: String(event.data.turn), role: 'update' }
    return null
  },
  start: (_context, match) => {
    if (match.event.type !== 'turn/start') throw new Error('audio-originals start requires turn/start')
    return { turn: match.event.data.turn, files: [], calls: new Map(), items: [] }
  },
  update: (context, match) => {
    const event = match.event
    if (event.type === 'tool/call') {
      if (event.data.name !== 'transcribe_audio' && event.data.name !== 'list_audio_files') return context.state
      const callId = String(event.data.callId)
      const call = callRecord(context.state.files, callId, event.data.name, event.data.arguments)
      const calls = new Map(context.state.calls)
      calls.set(callId, call)
      if (!call.transcribe) return { ...context.state, calls }
      const running: AudioTurnItem = { callId, seq: event.seq, state: 'running', file: call.file,
        ...(call.attachmentId === undefined ? {} : { attachmentId: call.attachmentId }) }
      return { ...context.state, calls, items: [...context.state.items, running] }
    }
    if (event.type !== 'tool/result') return context.state
    const callId = String(event.data.message.source.callId)
    const call = context.state.calls.get(callId)
    if (call === undefined) return context.state
    const remainingCalls = new Map(context.state.calls)
    remainingCalls.delete(callId)
    if (!call.transcribe) {
      if (event.data.message.isError === true) return { ...context.state, calls: remainingCalls }
      return { ...context.state, calls: remainingCalls, files: inventory(contentText(event.data.message.content)) }
    }
    let item: AudioTurnItem
    if (event.data.message.isError === true) {
      item = { callId, seq: event.seq, state: 'error', file: call.file,
        ...(call.attachmentId === undefined ? {} : { attachmentId: call.attachmentId }),
        error: resultText(event.data.message.content) }
    } else {
      const meta = event.data.meta
      if (typeof meta !== 'object' || meta === null || !('audioTranscript' in meta) || meta.audioTranscript !== true
        || !('source' in meta) || typeof meta.source !== 'string'
        || !('file' in meta) || typeof meta.file !== 'string'
        || !('model' in meta) || typeof meta.model !== 'string'
        || !('text' in meta) || typeof meta.text !== 'string') return context.state
      const attachmentId = typeof meta.attachmentId === 'string'
        ? meta.attachmentId
        : call.attachmentId ?? (call.filePath === true ? undefined : `sha256:${meta.source}`)
      item = { callId, seq: event.seq, state: 'success', file: meta.file, model: meta.model,
        source: meta.source, text: meta.text,
        ...(attachmentId === undefined ? {} : { attachmentId }) }
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
      && previous.key === 'audio-originals' && previous.value.items === context.state.items) return previous
    return { kind: 'turn', turn: context.state.turn, key: 'audio-originals', value: { items: context.state.items } }
  },
}
