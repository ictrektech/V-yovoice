import { describe, expect, it } from 'vitest'
import { resolveApiPath } from './api'

describe('resolveApiPath', () => {
  it('keeps local development requests at the site root', () => {
    expect(resolveApiPath('/api/v1/models', '/')).toBe('/api/v1/models')
  })

  it('keeps requests inside the VOS application prefix', () => {
    expect(resolveApiPath('/api/v1/models', '/app/com.ictrek.v-voice/')).toBe('/app/com.ictrek.v-voice/api/v1/models')
    expect(resolveApiPath('/v1/audio/speech', '/app/com.ictrek.v-voice')).toBe('/app/com.ictrek.v-voice/v1/audio/speech')
  })
})
