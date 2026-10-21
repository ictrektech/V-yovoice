import { useEffect, useState } from 'react';
import { useTranslator } from '@astryxdesign/core/i18n';

// 只读取脱敏状态；服务凭据不进入浏览器，等待交接期间模型管理仍然可用。
export function SchedulerStatus() {
  const t = useTranslator();
  const [configured, setConfigured] = useState<boolean>();
  const [needsModels, setNeedsModels] = useState(false);
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
        if (status?.configured === false) {
          const [discovery, creative] = await Promise.all([
            fetch('./api/v1/discovery', { signal: controller.signal, cache: 'no-store' }),
            fetch('./api/v1/creative-models', { signal: controller.signal, cache: 'no-store' }),
          ]);
          if (discovery.ok && creative.ok) {
            const native = await discovery.json() as { models?: unknown[] };
            const rows = await creative.json() as { status?: string }[];
            if (active) setNeedsModels(Array.isArray(native.models) && native.models.length === 0 && Array.isArray(rows) && !rows.some(row => row.status === 'ready'));
          } else if (active) setNeedsModels(false);
        } else if (active) setNeedsModels(false);
      } catch { if (active) { setConfigured(false); setNeedsModels(false); } }
      finally { running = false; }
    }
    void update();
    const timer = setInterval(() => void update(), 5000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, []);
  if (configured === true) return null;
  return <p role="status" aria-live="polite" data-testid="scheduler-status">{t(configured === undefined ? '@vvoice.scheduler.checking' : needsModels ? '@vvoice.scheduler.needsModels' : '@vvoice.scheduler.waiting')}</p>;
}
