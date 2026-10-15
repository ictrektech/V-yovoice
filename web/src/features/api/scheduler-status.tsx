import { useEffect, useState } from 'react';
import { useTranslator } from '@astryxdesign/core/i18n';

// 只读取脱敏状态；服务凭据不进入浏览器，等待交接期间模型管理仍然可用。
export function SchedulerStatus() {
  const t = useTranslator();
  const [configured, setConfigured] = useState<boolean>();
  useEffect(() => {
    let active = true;
    let running = false;
    const controller = new AbortController();
    async function update() {
      if (running) return;
      running = true;
      try {
        const response = await fetch('./api/v1/scheduler/binding', { signal: controller.signal, cache: 'no-store' });
        const status = response.ok ? await response.json() as { configured?: boolean } : undefined;
        if (active) setConfigured(status?.configured === true);
      } catch { if (active) setConfigured(false); }
      finally { running = false; }
    }
    void update();
    const timer = setInterval(() => void update(), 5000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, []);
  if (configured === true) return null;
  return <p role="status" aria-live="polite" data-testid="scheduler-status">{t(configured === undefined ? '@vvoice.scheduler.checking' : '@vvoice.scheduler.waiting')}</p>;
}
