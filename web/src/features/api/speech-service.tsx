import { VStack } from '@astryxdesign/core/Layout';
import { useLocale, useTranslator } from '@astryxdesign/core/i18n';
import type { SyntheticEvent } from 'react';
import { schedulerFetch, vosFetch } from '../../shared/lib/vos';
import { applyServiceTheme } from './service-theme';

export type SpeechPage = 'models' | 'asr' | 'tts' | 'speaker' | 'hotwords';

// 保留原有完整操作界面和接口，在主工作台内打开，不离开创作页。
export function SpeechService({ page, kind }: { page: SpeechPage; kind?: 'asr' | 'tts' | 'speaker' }) {
  const locale = useLocale();
  const t = useTranslator();
  function connect(event: SyntheticEvent<HTMLIFrameElement>) {
    applyServiceTheme(event);
    const frame = event.currentTarget;
    const document = frame.contentDocument;
    if (!document || !frame.contentWindow || !['asr', 'tts', 'speaker'].includes(page)) return;
    Object.assign(frame.contentWindow, {
      vvoiceCompute: {
        placements: (signal: AbortSignal) => page === 'asr'
          ? schedulerFetch('/api/v1/voice/compute/placements', { signal })
          : vosFetch(`/api/v1/compute/placements?task_type=${page === 'tts' ? 'voice.synthesize' : 'voice.speaker_embedding'}`, { signal }),
        transcribe: (body: FormData, signal: AbortSignal) =>
          schedulerFetch('/api/v1/voice/compute/transcriptions', { method: 'POST', body, signal }),
        speech: (body: string, signal: AbortSignal) =>
          vosFetch('/api/v1/compute/speech', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, signal }),
        speaker: (action: 'enroll' | 'identify' | 'verify', body: FormData, signal: AbortSignal) => {
          if (!['enroll', 'identify', 'verify'].includes(action)) throw new Error('Invalid speaker operation');
          return vosFetch(`/api/v1/compute/speakers/${action}`, { method: 'POST', body, signal });
        },
      },
    });
    document.dispatchEvent(new Event('vvoice-compute-ready'));
  }
  return <VStack style={{ flex: 1, minHeight: 0 }} data-testid={`speech-service-${page}`}>
    <iframe onLoad={connect} title={t(`@vvoice.nav.${page}`)} src={`./service/?page=${page}&standalone=1&locale=${encodeURIComponent(locale === 'en' ? 'en-US' : locale)}${kind ? `&kind=${kind}` : ''}`} style={{ width: '100%', flex: 1, minHeight: 0, border: 0 }} />
  </VStack>;
}
