import { useTranslator } from '@astryxdesign/core/i18n';
import { Selector } from '../../shared/selector';
import type { Draft, State, Track } from '../../shared/workbench';
import { AdvancedSettings, ReferenceVoice, SeedInput } from './shared-controls';
import { ModelOptions } from './model-options';

const languages = ['en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh-cn', 'hu', 'ko', 'ja', 'hi'];

export function XTTSControls({ draft, state, change, chooseVoice, play, advanced, setAdvanced }: { draft: Draft; state: State; change: (patch: Partial<Draft>) => void; chooseVoice: () => void; play: (track: Track) => void; advanced: boolean; setAdvanced: (open: boolean) => void }) {
  const t = useTranslator();
  const voice = state.voices.find(item => item.id === draft.voiceId);
  return <>
    <ReferenceVoice voice={voice} choose={chooseVoice} play={play} />
    <Selector label={t('@yovoice.create.language')} value={languages.includes(draft.synthesisLanguage ?? '') ? draft.synthesisLanguage! : 'zh-cn'} options={languages.map(value => ({ value, label: t(`@yovoice.language.${value}`) }))} onChange={synthesisLanguage => change({ synthesisLanguage })} />
    <AdvancedSettings open={advanced} onOpenChange={setAdvanced}>
      <ModelOptions draft={draft} family="xtts_v2" change={change} />
      <SeedInput value={draft.seed} change={change} max={4294967295} />
    </AdvancedSettings>
  </>;
}
