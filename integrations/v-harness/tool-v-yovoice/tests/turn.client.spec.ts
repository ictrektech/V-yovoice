import { expect, it } from 'vitest'
import type { ConversationMatch, ConversationStartMatch } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { audioTurnDefinition, type AudioTurnData } from '../src/client/turn.ts'

function start(turn = 1): ConversationStartMatch {
  return {
    event: { type: 'turn/start', seq: 1, time: 1, data: { turn } },
    role: 'start',
    location: { kind: 'turn', turn },
  } as never
}

function call(seq: number, callId: string, args: Record<string, unknown>, turn = 1, name = 'transcribe_audio'): ConversationMatch {
  return {
    event: {
      type: 'tool/call', seq, time: seq,
      data: { turn, step: 1, callId, name, arguments: JSON.stringify(args) },
    },
    role: 'update',
    location: { kind: 'turn', turn },
  } as never
}

function result(seq: number, callId: string, text: string, error = false, turn = 1): ConversationMatch {
  return {
    event: {
      type: 'tool/result', seq, time: seq, surfaceOp: 'append',
      data: {
        turn, step: 1,
        message: {
          role: 'tool', source: { kind: 'tool', callId }, toolCallId: callId,
          content: [{ type: 'text', text }], isError: error,
        },
        meta: error ? undefined : {
          audioTranscript: true, source: 'a'.repeat(64), attachmentId: `sha256:${'a'.repeat(64)}`,
          file: 'meeting.mp3', model: 'sensevoice-int8', text,
        },
      },
    },
    role: 'update',
    location: { kind: 'turn', turn },
  } as never
}

function inventoryResult(seq: number, callId: string, text: string, turn = 1): ConversationMatch {
  return {
    event: {
      type: 'tool/result', seq, time: seq, surfaceOp: 'append',
      data: {
        turn, step: 1,
        message: {
          role: 'tool', source: { kind: 'tool', callId }, toolCallId: callId,
          content: [{ type: 'text', text }], isError: false,
        },
      },
    },
    role: 'update',
    location: { kind: 'turn', turn },
  } as never
}

it('projects running, complete, and failed audio calls outside the tool group', () => {
  const started = audioTurnDefinition.start({} as never, start(), {} as never)
  const listed = audioTurnDefinition.update({ state: started } as never,
    call(2, 'list-a', {}, 1, 'list_audio_files'))
  const inventory = audioTurnDefinition.update({ state: listed } as never, inventoryResult(3, 'list-a',
    JSON.stringify([{ attachment_id: `sha256:${'a'.repeat(64)}`, name: 'meeting.mp3', bytes: 10 }])))
  const running = audioTurnDefinition.update({ state: inventory } as never,
    call(4, 'call-a', { attachment_id: `sha256:${'a'.repeat(64)}` }))
  expect(running.items[0]).toMatchObject({
    callId: 'call-a', state: 'running', file: 'meeting.mp3', attachmentId: `sha256:${'a'.repeat(64)}`,
  })

  const complete = audioTurnDefinition.update({ state: running } as never,
    result(5, 'call-a', 'first line\nsecond line'))
  expect(complete.items[0]).toMatchObject({ state: 'success', file: 'meeting.mp3', model: 'sensevoice-int8', text: 'first line\nsecond line' })

  const rerun = audioTurnDefinition.update({ state: complete } as never,
    call(6, 'call-b', { attachment_id: `sha256:${'a'.repeat(64)}` }))
  const failed = audioTurnDefinition.update({ state: rerun } as never,
    result(7, 'call-b', 'V-yovoice busy (HTTP 429)', true))
  expect(failed.items[0]).toMatchObject({ callId: 'call-a', state: 'success' })
  expect(failed.items[1]).toMatchObject({ callId: 'call-b', state: 'error', error: 'V-yovoice busy (HTTP 429)' })

  const published = audioTurnDefinition.buildLocationData!({ state: failed } as never, 'turn', null) as {
    value: AudioTurnData
  }
  expect(published.value.items).toEqual(failed.items)
})

it('does not create a card for unrelated calls', () => {
  const started = audioTurnDefinition.start({} as never, start(), {} as never)
  const unrelated = { ...call(2, 'other', {}), event: {
    ...call(2, 'other', {}).event, data: { turn: 1, step: 1, callId: 'other', name: 'read', arguments: '{}' },
  } } as ConversationMatch
  expect(audioTurnDefinition.update({ state: started } as never, unrelated)).toBe(started)
})
