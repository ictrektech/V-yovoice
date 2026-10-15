import { useSyncExternalStore } from 'react'
import { listenForVosBridgeLocale } from './vosBridge'
import {
  LANGUAGE_KEY, isVosLocaleKey, readLanguageMode, readVosLocale, resolveLocale,
  type LanguageMode, type Locale,
} from './vosLocale'

let bridgeLocale: Locale | null = null
const embedded = new URLSearchParams(window.location.search).get('standalone') === '1'
if (embedded) {
  document.documentElement.dataset.vvoiceDocs = 'true'
  document.documentElement.dataset.vvoicePage = new URLSearchParams(window.location.search).get('page') ?? 'models'
}
const requestedLocale = new URLSearchParams(window.location.search).get('locale')
let embeddedMode: LanguageMode = requestedLocale === 'zh-CN' || requestedLocale === 'zh-TW' || requestedLocale === 'en-US' ? requestedLocale : 'auto'

function currentLanguage() {
  let mode: LanguageMode = 'auto'
  let hostLocale = bridgeLocale
  try {
    mode = embedded ? embeddedMode : readLanguageMode(window.localStorage)
    if (window.location.pathname.includes('/app/com.ictrek.v-voice')) {
      hostLocale = bridgeLocale ?? readVosLocale(window.localStorage)
    }
  } catch { /* Use the browser language when storage access is blocked. */ }
  return { mode, locale: resolveLocale(mode, hostLocale, navigator.languages || [navigator.language]) }
}

let language = currentLanguage()
const listeners = new Set<() => void>()
let stopBridge: (() => void) | undefined

function refreshLanguage() {
  const next = currentLanguage()
  if (next.mode === language.mode && next.locale === language.locale) return
  language = next
  document.documentElement.lang = next.locale
  listeners.forEach(listener => listener())
}

function onStorage(event: StorageEvent) {
  if (event.key === null || event.key === LANGUAGE_KEY || isVosLocaleKey(event.key)) refreshLanguage()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (listeners.size === 1) {
    window.addEventListener('storage', onStorage)
    window.addEventListener('languagechange', refreshLanguage)
    window.addEventListener('focus', refreshLanguage)
    stopBridge = listenForVosBridgeLocale(locale => {
      bridgeLocale = locale
      refreshLanguage()
    })
    refreshLanguage()
  }
  return () => {
    listeners.delete(listener)
    if (!listeners.size) {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('languagechange', refreshLanguage)
      window.removeEventListener('focus', refreshLanguage)
      stopBridge?.()
      stopBridge = undefined
    }
  }
}

export function useLanguage() {
  return useSyncExternalStore(subscribe, () => language)
}

export function setLanguageMode(mode: LanguageMode) {
  if (embedded) { embeddedMode = mode; refreshLanguage(); return }
  try {
    if (mode === 'auto') window.localStorage.removeItem(LANGUAGE_KEY)
    else window.localStorage.setItem(LANGUAGE_KEY, mode)
    refreshLanguage()
  } catch {
    language = { mode, locale: resolveLocale(mode, null, navigator.languages || [navigator.language]) }
    document.documentElement.lang = language.locale
    listeners.forEach(listener => listener())
  }
}

document.documentElement.lang = language.locale
