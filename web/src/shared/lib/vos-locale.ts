import type { UiLocale } from '../workbench';
import { isUiLocale, resolveInitialUiLocale } from '../i18n/locale';

const key = 'v-voice-creator-locale';
export type VosLocalePreference = UiLocale | 'auto';
export function vosLocalePreference(): VosLocalePreference {
  const value = localStorage.getItem(key);
  return isUiLocale(value) ? value : 'auto';
}
export function setVosLocalePreference(value: VosLocalePreference) {
  localStorage.setItem(key, value);
  window.dispatchEvent(new Event('v-voice-locale-preference'));
}

// 旧版 VOS 没有语言桥接能力，沿用平台自己的语言偏好键；不读取其他存储项。
function legacyVosLocale(): UiLocale | undefined {
  if (window.parent === window) return;
  try {
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((name): name is string => name === 'preferences-locale' ||
        !!name && ['VIVIBIT-', 'vben-web-antd-'].some(prefix => name.startsWith(prefix) && name.endsWith('-preferences-locale')))
      .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
    for (const name of keys) {
      const raw = localStorage.getItem(name);
      let value: unknown = raw;
      try { const parsed: unknown = JSON.parse(raw ?? 'null'); value = parsed && typeof parsed === 'object' && 'value' in parsed ? parsed.value : parsed; } catch { /* 兼容未包装的语言字符串。 */ }
      if (typeof value === 'string' && /^(zh(?:[-_](?:cn|sg|hans|tw|hk|mo|hant))?(?:[-_].*)?|en(?:[-_].*)?)$/i.test(value.trim())) {
        return resolveInitialUiLocale(value.trim().replaceAll('_', '-'));
      }
    }
  } catch { /* 存储不可读时仍可使用平台桥接。 */ }
}

// 先订阅再读取快照；旧快照不得覆盖期间收到的平台语言事件。
export function listenVosLocale(apply: (locale: UiLocale) => void) {
  let active = true;
  let revision = 0;
  let platformLocale: UiLocale | undefined;
  let stop: (() => void) | undefined;
  const update = () => {
    if (active) {
      const preference = vosLocalePreference();
      apply(preference === 'auto' ? platformLocale ?? legacyVosLocale() ?? resolveInitialUiLocale(navigator.language) : preference);
    }
  };
  const accept = (state: { locale?: unknown }) => {
    if (typeof state.locale !== 'string') return;
    const locale = state.locale.toLowerCase();
    if (!locale.startsWith('zh') && !locale.startsWith('en')) return;
    platformLocale = resolveInitialUiLocale(locale);
    update();
  };
  const connect = () => {
    const bridge = window.vos_platform;
    if (!bridge?.getState && !bridge?.broadcast) return false;
    stop = bridge.broadcast?.on('locale-change', state => { revision++; accept(state); });
    const snapshotRevision = revision;
    void bridge.getState?.().then(state => { if (active && revision === snapshotRevision) accept(state); }).catch(() => undefined);
    return true;
  };
  const started = Date.now();
  const timer = connect() ? undefined : setInterval(() => {
    if (connect() || Date.now() - started > 10000) clearInterval(timer);
  }, 50);
  window.addEventListener('v-voice-locale-preference', update);
  window.addEventListener('storage', update);
  window.addEventListener('focus', update);
  update();
  return () => { active = false; clearInterval(timer); stop?.(); window.removeEventListener('v-voice-locale-preference', update); window.removeEventListener('storage', update); window.removeEventListener('focus', update); };
}
