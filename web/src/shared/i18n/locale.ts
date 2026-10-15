import type { UiLocale } from '../workbench';

/** First-launch default from navigator.language. */
export function resolveInitialUiLocale(navigatorLanguage: string): UiLocale {
  const tag = navigatorLanguage.trim().toLowerCase();
  if (tag === 'zh-tw' || tag === 'zh-hk' || tag.includes('hant')) return 'zh-TW';
  return tag === 'zh' || tag.startsWith('zh-') ? 'zh-CN' : 'en';
}

/** Boundary parse for preferences.uiLocale (JSON / RPC). */
export function parseUiLocale(raw: unknown): UiLocale {
  if (isUiLocale(raw)) return raw;
  throw new Error(`unsupported uiLocale: ${String(raw)}`);
}

export function isUiLocale(raw: unknown): raw is UiLocale {
  return raw === 'zh-CN' || raw === 'zh-TW' || raw === 'en';
}
