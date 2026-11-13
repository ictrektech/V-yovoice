import { expect, it, vi } from 'vitest'
import { stubConfigForm } from '@deepseek-ai/dsh-client-test-runtime'
import { audioForm, type AudioSettings } from '../src/client/form.ts'

it('stages profile changes, saves one atomic patch, and releases its subscription', async () => {
  const host = stubConfigForm<AudioSettings>()
  const defaults = { baseUrl: '', model: '', requestTimeoutMs: 1860000, maxUploadBytes: 209715200, maxResponseBytes: 16777216, pageCharacters: 12000 }
  host.publish({ status: 'ready', writable: true, value: defaults, base: defaults, user: {} })
  const form = audioForm(host.scope)
  expect(form.store.getSnapshot()).toMatchObject({ available: true, dirty: false })
  form.actions.edit('baseUrl', 'http://voice:7070')
  form.actions.edit('model', 'sensevoice-int8')
  expect(host.mutate).not.toHaveBeenCalled()
  form.actions.save()
  await vi.waitFor(() => { expect(host.mutate).toHaveBeenCalledOnce() })
  expect(host.mutate.mock.calls[0]?.[0]).toEqual([
    { op: 'set', path: ['baseUrl'], value: 'http://voice:7070' },
    { op: 'set', path: ['model'], value: 'sensevoice-int8' },
  ])
  form.actions.edit('pageCharacters', 'not-a-number')
  expect(form.store.getSnapshot().invalid).toBe(true)
  form.actions.discard()
  expect(form.store.getSnapshot().dirty).toBe(false)
  form.form.dispose()
  expect(host.listenerCount()).toBe(0)
})
