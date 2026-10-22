import { useEffect, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { AppDialog } from '../shared/ui/app-dialog';

type AboutInfo = { app_id: string; app_version: string; profile: string; provider: string };
type BindingStatus = { configured?: boolean };

// 关于对话框读取服务注入的运行信息：版本来自 APP_VERSION，网关状态来自调度器绑定。
export function AboutDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslator();
  const [info, setInfo] = useState<AboutInfo>();
  const [configured, setConfigured] = useState<boolean>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch('./api/v1/about', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('About unavailable');
        const about = await response.json() as AboutInfo;
        if (!controller.signal.aborted) setInfo(about);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    void (async () => {
      try {
        const response = await fetch('./api/v1/scheduler/binding', { signal: controller.signal, cache: 'no-store' });
        if (response.ok) {
          const binding = await response.json() as BindingStatus;
          if (!controller.signal.aborted) setConfigured(binding.configured === true);
        }
      } catch { /* 调度器尚未绑定时只显示未配置 */ }
    })();
    return () => controller.abort();
  }, []);
  const gateway = configured === undefined ? '—' : t(configured ? '@yovoice.app.aboutGatewayConnected' : '@yovoice.app.aboutGatewayMissing');
  const rows: [string, string][] = [
    [t('@yovoice.app.aboutVersion'), info?.app_version || '—'],
    [t('@yovoice.app.aboutAppId'), info?.app_id || 'com.ictrek.v-voice'],
    [t('@yovoice.app.aboutProfile'), info?.profile || '—'],
    [t('@yovoice.app.aboutInference'), info?.provider || '—'],
    [t('@yovoice.app.aboutGateway'), `V-Scheduler · ${gateway}`],
  ];
  return <AppDialog title={t('@yovoice.app.aboutTitle')} subtitle={t('@yovoice.app.aboutSubtitle')} width={480} onClose={onClose} actions={<Button label={t('@yovoice.action.close')} onClick={onClose} />}>
    <VStack className="settings-rows about-rows" gap={0}>
      {rows.map(([label, value]) => <HStack key={label} className="settings-row about-row" hAlign="between" vAlign="center" gap={4}>
        <p className="settings-row-title">{label}</p>
        <p className="about-value">{value}</p>
      </HStack>)}
    </VStack>
    {failed ? <p className="helper" role="status">{t('@yovoice.app.aboutUnavailable')}</p> : null}
  </AppDialog>;
}
