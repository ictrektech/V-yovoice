import { VStack } from '@astryxdesign/core/Layout';
import { TextArea } from '@astryxdesign/core/TextArea';
import { useTranslator } from '@astryxdesign/core/i18n';
import type { Draft } from '../../shared/workbench';

// 音效作品的正文：只有一段英文描述，时长与生成方式在检查器里。
export function SfxEditor({ draft, change }: { draft: Draft; change: (patch: Partial<Draft>) => void }) {
  const t = useTranslator();
  return <VStack className="music-editor sfx-editor" gap={5}>
    <VStack className="music-block" gap={3}>
      <h2>{t('@yovoice.music.soundDescription')}</h2>
      <TextArea className="music-lyrics" label={t('@yovoice.music.soundDescription')} isLabelHidden value={draft.text} maxLength={512} rows={14} hasSpellCheck={false} placeholder={t('@yovoice.music.soundPlaceholder')} onChange={text => change({ text: text.slice(0, 512) })} />
    </VStack>
  </VStack>;
}
