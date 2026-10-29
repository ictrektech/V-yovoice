import { Button } from '@astryxdesign/core/Button';
import { VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { AppDialog } from '../../shared/ui/app-dialog';
import { isAligner, isMusicModel, isSoundFont, isTranscriber, isVoiceModel, projectKind, type Draft, type ModelPackage, type State } from '../../shared/workbench';
import { useSharedModelInventory } from '../../shared/lib/model-inventory';
import { ModelGroups } from '../settings/model-list';
import { SpeechService } from './speech-service';

// 按当前功能筛选，并复用现有下载、暂停、重试及校验状态；关闭后留在原页面。
export function PrepareModels({ page, state, catalog, draft, run, close }: {
  page: string; state: State; catalog: ModelPackage[]; draft: Draft;
  run: (task: () => Promise<unknown>) => void; close: () => void;
}) {
  const t = useTranslator();
  const speech = page === 'hotwords' || page === 'asr' ? 'asr' : page === 'tts' ? 'tts' : page === 'speaker' ? 'speaker' : undefined;
  const kind = page === 'create' || page === 'history' ? projectKind(draft) : page;
  const all = page === 'settings' || page === 'api-docs';
  const models = catalog.filter(model => all || (kind === 'music' ? isMusicModel(model.id) || isAligner(model.id) || isTranscriber(model.id) || isSoundFont(model.id) : kind === 'sfx' ? model.family === 'stable_audio' && (model.variant === 'sfx' || model.variant === 'medium') : kind === 'score' ? model.family === 'soundfont' : isVoiceModel(model.id)));
  const { models: shared, failed } = useSharedModelInventory(!speech);
  return <AppDialog title={t('@vvoice.models.prepare')} width="calc(var(--spacing-10) * 22)" closeLabel={t('@yovoice.action.close')} onClose={close}
    actions={<Button label={t('@yovoice.action.close')} onClick={close} />}>
    <VStack gap={3} style={{ height: '60dvh', overflowY: 'auto', minHeight: 0 }} data-testid="prepare-models-panel">
      {speech ? <SpeechService page="models" kind={speech} /> : <>
        <p style={{ flexShrink: 0 }}>{t('@vvoice.models.prepareHint')}</p>
        {failed ? <p role="alert">{t('@vvoice.models.inventoryError')}</p> : null}
        <ModelGroups models={models} state={state} draft={draft} run={run} shared={shared} />
      </>}
    </VStack>
  </AppDialog>;
}
