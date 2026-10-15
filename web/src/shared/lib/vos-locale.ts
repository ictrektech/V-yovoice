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

// 先订阅再读取快照；旧快照不得覆盖期间收到的平台语言事件。
export function listenVosLocale(apply: (locale: UiLocale) => void) {
  let active = true;
  let revision = 0;
  let platformLocale: UiLocale = resolveInitialUiLocale(navigator.language);
  let stop: (() => void) | undefined;
  const update = () => {
    if (active) {
      const preference = vosLocalePreference();
      apply(preference === 'auto' ? platformLocale : preference);
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
  update();
  return () => { active = false; clearInterval(timer); stop?.(); window.removeEventListener('v-voice-locale-preference', update); };
}
