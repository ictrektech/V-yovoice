import { createDraft, type Draft, type UiLocale } from '../../shared/workbench';

export const sfxModelId = 'stable-audio-3-small-sfx-q8';
export const sfxDurationPresets = [1, 3, 5, 10, 30] as const;

export function createSfxDraft(locale: UiLocale): Draft {
  return {
    ...createDraft(false, locale, sfxModelId),
    kind: 'sfx',
    text: '',
    instrumental: true,
    synthesisLanguage: 'en',
    modelOptions: { stable_audio: { duration_seconds: 5 } },
  };
}
