import { useTranslator } from '@astryxdesign/core/i18n';
import { Selector } from '../../shared/selector';
import type { Draft, ModelPackage } from '../../shared/workbench';
import { AdvancedSettings, SeedInput } from './shared-controls';
import { ModelOptions } from './model-options';

const voiceGroups = [
  ['general', ['casual_female', 'casual_male', 'cheerful_female', 'neutral_female', 'neutral_male']],
  ['pt', ['pt_male', 'pt_female']],
  ['nl', ['nl_male', 'nl_female']],
  ['it', ['it_male', 'it_female']],
  ['fr', ['fr_male', 'fr_female']],
  ['es', ['es_male', 'es_female']],
  ['de', ['de_male', 'de_female']],
  ['ar', ['ar_male']],
  ['hi', ['hi_male', 'hi_female']],
] as const;

export function VoxtralControls({ draft, model, change, advanced, setAdvanced }: { draft: Draft; model: ModelPackage; change: (patch: Partial<Draft>) => void; advanced: boolean; setAdvanced: (open: boolean) => void }) {
  const t = useTranslator();
  const voices = new Set(model.voices ?? []);
  return <>
    <Selector label={t('@yovoice.reference.speaker')} value={draft.speaker || 'casual_male'} options={voiceGroups.map(([language, items]) => ({
      type: 'section', title: t(language === 'general' ? '@yovoice.voxtral.generalVoices' : `@yovoice.language.${language}`),
      options: items.filter(voice => voices.has(voice)).map(value => ({ value, label: value })),
    }))} onChange={speaker => change({ speaker })} />
    <AdvancedSettings open={advanced} onOpenChange={setAdvanced}>
      <ModelOptions draft={draft} family="voxtral_tts" change={change} />
      <SeedInput value={draft.seed} change={change} />
    </AdvancedSettings>
  </>;
}
