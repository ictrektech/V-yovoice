import { useTranslator } from '@astryxdesign/core/i18n';
import { Selector } from '../../shared/selector';
import type { Draft } from '../../shared/workbench';
import { AdvancedSettings, SeedInput } from './shared-controls';
import { ModelOptions } from './model-options';

export function GradiumControls({ draft, change, advanced, setAdvanced }: { draft: Draft; change: (patch: Partial<Draft>) => void; advanced: boolean; setAdvanced: (open: boolean) => void }) {
  const t = useTranslator();
  return <>
    <Selector label={t('@yovoice.create.language')} value="en" options={[{ value: 'en', label: t('@yovoice.language.en') }]} isDisabled onChange={() => {}} />
    <AdvancedSettings open={advanced} onOpenChange={setAdvanced}>
      <ModelOptions draft={draft} family="gradium_phonon" change={change} />
      <SeedInput value={draft.seed} change={change} max={4294967295} />
    </AdvancedSettings>
  </>;
}
