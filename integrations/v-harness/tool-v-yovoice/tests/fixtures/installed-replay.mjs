/** Test-only scripted LLM adapter for a one-shot installed-package smoke. */
import { createRequire } from 'node:module'
const manifest = process.env.AUDIO_SMOKE_RUNTIME_MANIFEST
if (!manifest) throw new Error('AUDIO_SMOKE_RUNTIME_MANIFEST is required')
const require = createRequire(manifest)
const { LlmAdapter, ToolCallId } = await import(require.resolve('@deepseek-ai/dsh-llm'))

export const inject = ['llm']
export function apply(ctx) {
  class Adapter extends LlmAdapter {
    step = 0
    async resolveModel(provider, model) { return { provider, id: model, name: model } }
    async *stream(options) {
      if (this.step++ === 0) {
        const block = { type: 'tool-call', id: ToolCallId('audio-acceptance'), name: 'transcribe_audio', arguments: JSON.stringify({ file_path: process.env.AUDIO_SMOKE_PATH ?? '/tmp/vh-audio-acceptance/sample.mp3' }) }
        yield { type: 'block-start', index: 0, blockType: 'tool-call' }
        yield { type: 'block-end', index: 0, block }
        yield { type: 'finish', reason: { kind: 'tool-calls' } }
        return
      }
      const body = JSON.stringify(options.messages)
      const expectedError = process.env.AUDIO_SMOKE_EXPECT_ERROR
      if (!body.includes(expectedError ?? 'meeting starts at 9 tomorrow')) throw new Error('Installed audio tool did not return the expected transcript or failure')
      const block = { type: 'text', text: expectedError ? `Expected service error: ${expectedError}` : 'Hello, this is a test of audio transcription. The meeting starts at 9 tomorrow.' }
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: block.text }
      yield { type: 'block-end', index: 0, block }
      yield { type: 'finish', reason: { kind: 'stop' } }
    }
  }
  ctx.llm.registerAdapter(['audio-acceptance'], new Adapter())
}
