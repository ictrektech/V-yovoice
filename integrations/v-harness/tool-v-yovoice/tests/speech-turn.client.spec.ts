import { expect, it } from 'vitest'
import type { ConversationMatch, ConversationStartMatch } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { speechTurnDefinition, type SpeechTurnData } from '../src/client/speech-turn.ts'

function start(turn = 1): ConversationStartMatch {
  return {
    event: { type: 'turn/start', seq: 1, time: 1, data: { turn } },
    role: 'start',
    location: { kind: 'turn', turn },
  } as never
}

function call(seq: number, callId: string, args: Record<string, unknown>): ConversationMatch {
  return {
    event: {
      type: 'tool/call', seq, time: seq,
      data: { turn: 1, step: 1, callId, name: 'yovoice_speak', arguments: JSON.stringify(args) },
    },
    role: 'update',
    location: { kind: 'turn', turn: 1 },
  } as never
}

function result(seq: number, callId: string, text: string, failure = false): ConversationMatch {
  return {
    event: {
      type: 'tool/result', seq, time: seq, surfaceOp: 'append',
      data: {
        turn: 1, step: 1,
        message: {
          role: 'tool', source: { kind: 'tool', callId }, toolCallId: callId,
          content: [{ type: 'text', text }], isError: failure,
        },
        meta: failure ? undefined : {
          audioSpeech: true, attachmentId: `sha256:${'c'.repeat(64)}`, file: 'speech-test.wav',
          model: 'kokoro', voice: 'zf_xiaoxiao', text: '你好', bytes: 12,
        },
      },
    },
    role: 'update',
    location: { kind: 'turn', turn: 1 },
  } as never
}

it('projects running, successful and failed speech calls outside the tool group', () => {
  const started = speechTurnDefinition.start({} as never, start(), {} as never)
  const running = speechTurnDefinition.update({ state: started } as never,
    call(2, 'speech-a', { text: '你好', voice: 'zf_xiaoxiao' }))
  expect(running.items[0]).toMatchObject({ callId: 'speech-a', state: 'running', text: '你好', voice: 'zf_xiaoxiao' })

  const complete = speechTurnDefinition.update({ state: running } as never, result(3, 'speech-a', 'ok'))
  expect(complete.items[0]).toMatchObject({
    state: 'success', attachmentId: `sha256:${'c'.repeat(64)}`, file: 'speech-test.wav',
    model: 'kokoro', voice: 'zf_xiaoxiao', text: '你好', bytes: 12,
  })

  const rerun = speechTurnDefinition.update({ state: complete } as never,
    call(4, 'speech-b', { text: '失败' }))
  const failed = speechTurnDefinition.update({ state: rerun } as never, result(5, 'speech-b', 'busy', true))
  expect(failed.items[0]).toMatchObject({ callId: 'speech-a', state: 'success' })
  expect(failed.items[1]).toMatchObject({ callId: 'speech-b', state: 'error', error: 'busy' })

  const published = speechTurnDefinition.buildLocationData!({ state: failed } as never, 'turn', null) as {
    value: SpeechTurnData
  }
  expect(published.value.items).toEqual(failed.items)
})
