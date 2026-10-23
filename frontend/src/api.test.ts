import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, resolveApiPath } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('resolveApiPath', () => {
  it('keeps local development requests at the site root', () => {
    expect(resolveApiPath('/api/v1/models', '/')).toBe('/api/v1/models')
  })

  it('keeps requests inside the VOS application prefix', () => {
    expect(resolveApiPath('/api/v1/models', '/app/com.ictrek.v-voice/')).toBe('/app/com.ictrek.v-voice/api/v1/models')
    expect(resolveApiPath('/v1/audio/speech', '/app/com.ictrek.v-voice')).toBe('/app/com.ictrek.v-voice/v1/audio/speech')
  })
})

it('显示网关原始错误消息，不把资源不足改写为普通 HTTP 错误', async () => {
  vi.stubGlobal('window', { location: { pathname: '/' } })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'WAIT_MEMORY_HEADROOM' } }), { status: 429 })))
  await expect(api.models()).rejects.toThrow('WAIT_MEMORY_HEADROOM')
})
