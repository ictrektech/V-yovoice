import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PartialArguments } from '@deepseek-ai/dsh-util-values'
import type { ToolResultNode } from '@deepseek-ai/dsh-client-ui-chat/client'
import type {} from '../src/client/locales.ts'
import { AudioTranscriptResult as ProductToolCard, AudioTurnOriginalCard } from '../src/client/Views.tsx'

it('renders complete verbatim audio text as escaped text, independently of model preview length', () => {
  const text = '第一段\n<script>untrusted()</script>\n' + '完整原文'.repeat(4000)
  const block: ToolResultNode = {
    kind: 'tool-result', seq: 1, time: 1, callId: 'audio-1', name: 'transcribe_audio',
    args: PartialArguments.fromObject({}), call: null, callTime: null, content: [], isError: false, subCalls: [],
    meta: { audioTranscript: true, file: 'meeting.mp3', model: 'sensevoice', text },
  }
  const t: Parameters<typeof ProductToolCard>[0]['t'] = key => key
  const props = { block, t }
  const html = renderToStaticMarkup(ProductToolCard(props))
  expect(html).toContain('meeting.mp3')
  expect(html).toContain('&lt;script&gt;untrusted()&lt;/script&gt;')
  expect(html).not.toContain('<script>')
  expect(html.split('完整原文')).toHaveLength(4001)
  const failed = renderToStaticMarkup(ProductToolCard({ ...props,
    block: { ...block, isError: true, meta: undefined, content: [{ type: 'text', text: 'V-yovoice busy (HTTP 429)' }] },
  }))
  expect(failed).toContain('failed')
  expect(failed).toContain('V-yovoice busy (HTTP 429)')
})

it('renders one player with the complete original and no autoplay', () => {
  const attachmentId = `sha256:${'b'.repeat(64)}`
  const t: Parameters<typeof ProductToolCard>[0]['t'] = key => key
  const html = renderToStaticMarkup(<AudioTurnOriginalCard
    item={{
      callId: 'call-a', seq: 2, state: 'success', attachmentId, file: 'meeting.mp3',
      model: 'sensevoice-int8', source: 'b'.repeat(64), text: '第一行\n第二行',
    }}
    sessionId={'session-a' as never}
    savedTranscript={async () => null}
    t={t}
  />)
  expect(html).toContain('<audio')
  expect(html).toContain('preload="metadata"')
  expect(html).toContain('type="range"')
  expect(html).toContain('aria-label="play"')
  expect(html).toContain('aria-label="seek"')
  expect(html).not.toContain('autoplay')
  expect(html).toContain('meeting.mp3')
  expect(html).toContain('第一行\n第二行')
})

it('keeps the original available when an uploaded source cannot be played', () => {
  const t: Parameters<typeof ProductToolCard>[0]['t'] = key => key
  const html = renderToStaticMarkup(<AudioTurnOriginalCard
    item={{ callId: 'call-b', seq: 2, state: 'success', file: 'local.wav', model: 'sensevoice-int8', text: 'hello' }}
    sessionId={'session-a' as never}
    savedTranscript={async () => null}
    t={t}
  />)
  expect(html).toContain('playbackUnavailable')
  expect(html).not.toContain('<audio')
  expect(html).toContain('hello')
})
