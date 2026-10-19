import { useEffect, useState } from 'react';
import { VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import type { Draft, ModelPackage, State } from '../../shared/workbench';
import { ModelGroups, type SharedModelStatus } from '../settings/model-list';
import { SpeechService } from './speech-service';
import { NativeMusicModels } from '../music/background-music';

// 同一管理入口覆盖旧语音模型与全部创作精度/音色库；状态以共享文件校验结果为准。
export function ModelManagement({ category, state, catalog, draft, run }: { category: 'speech' | 'creative'; state: State; catalog: ModelPackage[]; draft: Draft; run: (task: () => Promise<unknown>) => void }) {
  const t = useTranslator();
  const [shared, setShared] = useState<Record<string, SharedModelStatus>>({});
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (category !== 'creative') return;
    let active = true;
    let running = false;
    const controller = new AbortController();
    async function update() {
      if (running) return;
      running = true;
      try {
        const response = await fetch('./api/v1/creative-models', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Shared inventory unavailable');
        const rows = await response.json() as Array<SharedModelStatus & { key: string }>;
        if (active) { setShared(Object.fromEntries(rows.map(row => [row.key.replace(/^audiocpp-/, ''), row]))); setFailed(false); }
      } catch { if (active) setFailed(true); }
      finally { running = false; }
    }
    void update();
    const timer = setInterval(() => void update(), 3000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, [category]);
  return <VStack gap={3} style={{ flex: 1, minHeight: 0 }} data-testid="model-management">
    {category === 'speech' ? <VStack id="speech-models-panel" style={{ flex: 1, minHeight: 0 }}><SpeechService page="models" /></VStack>
      : <VStack id="creative-models-panel" className="settings-page" gap={6} style={{ overflowY: 'auto' }}>
        <VStack as="header" gap={2} style={{ height: 'auto', alignItems: 'stretch' }}><h1>{t('@vvoice.models.creativeTab')}</h1><p>{t('@vvoice.models.sharedHint')}</p><a href="https://modelscope.cn/models/vivibit/v-voice-audiocpp-gguf" target="_blank" rel="noreferrer">ModelScope · vivibit/v-voice-audiocpp-gguf</a></VStack>
        {failed ? <p role="alert">{t('@vvoice.models.inventoryError')}</p> : null}
        <NativeMusicModels />
        <ModelGroups models={catalog} state={state} draft={draft} run={run} shared={shared} />
      </VStack>}
  </VStack>;
}
