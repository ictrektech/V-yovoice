import { describe, expect, it } from 'vitest'
import { isVosLocaleKey, normalizeLocale, parseStoredLocale, readLanguageMode, readVosLocale, resolveLocale } from './vosLocale'

function storage(entries: Record<string, string>): Storage {
  const values = new Map(Object.entries(entries))
  return {
    get length() { return values.size },
    key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value) },
    removeItem: key => { values.delete(key) },
    clear: () => values.clear(),
  }
}

describe('VOS locale resolution', () => {
  it('normalizes Chinese scripts and English regions', () => {
    for (const locale of ['zh-TW', 'zh-HK', 'zh-MO', 'zh-Hant', 'zh_Hant_TW']) expect(normalizeLocale(locale)).toBe('zh-TW')
    for (const locale of ['zh', 'zh-CN', 'zh-SG', 'zh-Hans-CN']) expect(normalizeLocale(locale)).toBe('zh-CN')
    for (const locale of ['en', 'en-US', 'en-GB']) expect(normalizeLocale(locale)).toBe('en-US')
    expect(normalizeLocale('ja-JP')).toBeNull()
  })

  it('reads wrapped, JSON-string and raw VOS preferences', () => {
    expect(parseStoredLocale('{"value":"en-US"}')).toBe('en-US')
    expect(parseStoredLocale('"zh-TW"')).toBe('zh-TW')
    expect(parseStoredLocale('zh-CN')).toBe('zh-CN')
    expect(parseStoredLocale('{broken')).toBeNull()
  })

  it('recognizes current and legacy keys and favors the latest version', () => {
    expect(isVosLocaleKey('VIVIBIT-5.5.9-prod-preferences-locale')).toBe(true)
    expect(isVosLocaleKey('vben-web-antd-5.0-prod-preferences-locale')).toBe(true)
    expect(isVosLocaleKey('preferences-locale')).toBe(true)
    expect(isVosLocaleKey('v-voice-language')).toBe(false)
    const values = storage({
      'VIVIBIT-5.5.9-prod-preferences-locale': '{"value":"zh-CN"}',
      'VIVIBIT-5.5.10-prod-preferences-locale': '{"value":"en-US"}',
      'vben-web-antd-5.0-prod-preferences-locale': '{"value":"zh-TW"}',
    })
    expect(readVosLocale(values)).toBe('en-US')
  })

  it('lets the host win in auto mode and preserves a manual override', () => {
    expect(resolveLocale('auto', 'en-US', ['zh-CN'])).toBe('en-US')
    expect(resolveLocale('zh-TW', 'en-US', ['zh-CN'])).toBe('zh-TW')
    expect(readLanguageMode(storage({ 'v-voice-language': 'zh-TW' }))).toBe('zh-TW')
    expect(readLanguageMode(storage({ 'v-voice-language': 'invalid' }))).toBe('auto')
  })

  it('falls back through browser languages to Simplified Chinese', () => {
    expect(resolveLocale('auto', null, ['ja-JP', 'zh-Hant-TW', 'en-US'])).toBe('zh-TW')
    expect(resolveLocale('auto', null, ['en-GB'])).toBe('en-US')
    expect(resolveLocale('auto', null, ['fr-FR'])).toBe('zh-CN')
  })
})
