import { useEffect, useState } from 'react';
import { isVos } from './vos';

export type SharedModelStatus = { status: string; downloaded_bytes?: number; total_bytes?: number; error?: string };
type InventoryRow = SharedModelStatus & { key: string };

// VOS 的共享模型由 Model Hub 下载，本地状态没有下载活动；进度只能从服务端目录拉取。
export function useSharedModelInventory(active: boolean) {
  const [models, setModels] = useState<Record<string, SharedModelStatus>>({});
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!isVos || !active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let running = false;
    async function update() {
      if (running) return;
      running = true;
      try {
        const response = await fetch('./api/v1/creative-models', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Shared inventory unavailable');
        const rows = await response.json() as InventoryRow[];
        if (!controller.signal.aborted) { setModels(Object.fromEntries(rows.map(row => [row.key.replace(/^audiocpp-/, ''), row]))); setFailed(false); }
      } catch { if (!controller.signal.aborted) setFailed(true); }
      finally { running = false; if (!controller.signal.aborted) timer = setTimeout(() => void update(), 3000); }
    }
    void update();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [active]);
  return { models, failed };
}
