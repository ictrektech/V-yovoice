import { VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import type { Draft, ModelPackage, State } from '../../shared/workbench';
import { ModelGroups } from '../settings/model-list';
import { SpeechService } from './speech-service';
import { useSharedModelInventory } from '../../shared/lib/model-inventory';

// 同一管理入口覆盖旧语音模型与全部创作精度/音色库；状态以共享文件校验结果为准。
export function ModelManagement({ category, state, catalog, draft, run }: { category: 'speech' | 'creative'; state: State; catalog: ModelPackage[]; draft: Draft; run: (task: () => Promise<unknown>) => void }) {
  const t = useTranslator();
  const { models: shared, failed } = useSharedModelInventory(category === 'creative');
  return <VStack gap={3} style={{ flex: 1, minHeight: 0 }} data-testid="model-management">
    {category === 'speech' ? <VStack id="speech-models-panel" style={{ flex: 1, minHeight: 0 }}><SpeechService page="models" /></VStack>
      : <VStack id="creative-models-panel" className="settings-page" gap={6} style={{ overflowY: 'auto' }}>
        <VStack as="header" gap={2} style={{ height: 'auto', alignItems: 'stretch' }}><h1>{t('@vvoice.models.creativeTab')}</h1><p>{t('@vvoice.models.sharedHint')}</p><a href="https://modelscope.cn/models/vivibit/v-voice-audiocpp-gguf" target="_blank" rel="noreferrer">ModelScope · vivibit/v-voice-audiocpp-gguf</a></VStack>
        {failed ? <p role="alert">{t('@vvoice.models.inventoryError')}</p> : null}
        <ModelGroups models={catalog} state={state} draft={draft} run={run} shared={shared} />
      </VStack>}
  </VStack>;
}
