import { AdvancedSettings, SeedInput, ReferenceVoice } from './shared-controls';
import { ModelOptions } from './model-options';
import { Selector } from '../../shared/selector';
import { VStack } from '@astryxdesign/core/Layout';
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl';
import { TextArea } from '@astryxdesign/core/TextArea';
import { useTranslator } from '@astryxdesign/core/i18n';
import { isMingModel, type Draft, type State, type Track } from '../../shared/workbench';

// Breeze 与 Ming 共用设计和克隆结构；参考原文要求、描述用途与语言选项按模型区分。
export function DesignCloneControls({ draft, state, change, chooseVoice, play, advanced, setAdvanced }: {
  draft: Draft; state: State; change: (patch: Partial<Draft>) => void; chooseVoice: () => void;
  play: (track: Track) => void; advanced: boolean; setAdvanced: (value: boolean) => void;
}) {
  const t = useTranslator();
  const ming = isMingModel(draft.modelId);
  const cloning = draft.voiceMode === 'clone';
  const voice = state.voices.find(item => item.id === draft.voiceId);
  return <>
    <VStack gap={3}>
      <h3>{t('@yovoice.vox.generationMode')}</h3>
      <SegmentedControl label={t('@yovoice.vox.generationMode')} size="sm" layout="fill" value={cloning ? 'clone' : 'design'} onChange={value => change({ voiceMode: value as Draft['voiceMode'] })}>
        <SegmentedControlItem value="design" label={t('@yovoice.vox.design')} />
        <SegmentedControlItem value="clone" label={t('@yovoice.vox.clone')} />
      </SegmentedControl>
    </VStack>
    {cloning ? <>
      <ReferenceVoice voice={voice} choose={chooseVoice} play={play} />
      <TextArea label={t(ming ? '@yovoice.reference.transcript' : '@yovoice.vox.referenceText')} description={t(ming ? '@yovoice.reference.transcriptHelp' : '@yovoice.breeze.referenceTextHelp')} value={draft.referenceText ?? ''} onChange={referenceText => change({ referenceText: referenceText.slice(0, 2000) })} placeholder={t('@yovoice.vox.referenceTextPlaceholder')} rows={3} />
    </> : null}
    {!ming || !cloning ? <TextArea label={cloning ? t('@yovoice.vox.styleGuidance') : t('@yovoice.vox.voiceDescription')} description={t(ming ? '@yovoice.reference.voiceDesignHelp' : '@yovoice.breeze.instructionHelp')} value={draft.voiceDescription ?? ''} onChange={voiceDescription => change({ voiceDescription: voiceDescription.slice(0, 500) })} placeholder={cloning ? t('@yovoice.vox.stylePlaceholder') : t('@yovoice.breeze.voiceDescriptionPlaceholder')} rows={3} /> : null}
    {ming ? <Selector label={t('@yovoice.create.language')} value={draft.synthesisLanguage || 'auto'} options={['auto', 'zh', 'en', 'ja', 'ko', 'de', 'fr', 'es'].map(value => ({ value, label: value === 'auto' ? t('@yovoice.reference.auto') : t(`@yovoice.language.${value}`) }))} onChange={synthesisLanguage => change({ synthesisLanguage })} /> : null}
    <AdvancedSettings open={advanced} onOpenChange={setAdvanced}>
      <ModelOptions draft={draft} family={ming ? 'ming3_tts' : 'breeze_tts'} change={change} />
      <SeedInput value={draft.seed} change={change} />
    </AdvancedSettings>
  </>;
}
