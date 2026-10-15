import { VStack } from '@astryxdesign/core/Layout';
import { useLocale, useTranslator } from '@astryxdesign/core/i18n';
import { applyServiceTheme } from './service-theme';

export type SpeechPage = 'models' | 'asr' | 'tts' | 'speaker' | 'hotwords';

// 保留原有完整操作界面和接口，在主工作台内打开，不离开创作页。
export function SpeechService({ page }: { page: SpeechPage }) {
  const locale = useLocale();
  const t = useTranslator();
  return <VStack style={{ flex: 1, minHeight: 0 }} data-testid={`speech-service-${page}`}>
    <iframe onLoad={applyServiceTheme} title={t(`@vvoice.nav.${page}`)} src={`./service/?page=${page}&standalone=1&locale=${encodeURIComponent(locale === 'en' ? 'en-US' : locale)}`} style={{ width: '100%', flex: 1, minHeight: 0, border: 0 }} />
  </VStack>;
}
