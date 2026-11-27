import { useEffect, useState } from 'react';
import { HStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Selector } from '../../shared/selector';
import { selectWorkbenchNode, vosFetch, type WorkbenchNode } from '../../shared/lib/vos';

type Placement = WorkbenchNode & { node_name?: string | null; profile: string; model_id: string };
const choice = (row: Placement) => `${row.deployment_id}:${row.node_id}`;

export function WorkbenchExecutionNode({ actual, selected, busy, visible }: { actual?: string; selected?: string; busy: boolean; visible: boolean }) {
  const t = useTranslator();
  const [node, setNode] = useState<Placement>();
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const options = new Map(placements.map(row => [choice(row), row]));
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const response = await vosFetch('/api/v1/compute/placements?task_type=voice.workbench', { signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        const result: { items: Placement[] } = await response.json();
        if (!controller.signal.aborted) { setPlacements(result.items); setUnavailable(false); }
      } catch {
        if (!controller.signal.aborted) setUnavailable(true);
      } finally { pending = false; }
    }
    void refresh();
    const timer = window.setInterval(refresh, 4500);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      selectWorkbenchNode(undefined);
    };
  }, []);
  const stale = !!node && !options.has(choice(node));
  const label = (value: string) => t(`@yovoice.remoteVoice.${value}`);
  if (!visible) return null;
  return <HStack gap={2} wrap="wrap" vAlign="end">
    <Selector label={label('workbenchNode')} value={node ? choice(node) : 'local'} isDisabled={busy} size="sm"
      options={[
        { value: 'local', label: label('primary') },
        ...Array.from(options, ([value, row]) => ({ value, label: `${row.node_name || row.node_id} · ${row.profile}` })),
        ...(stale ? [{ value: choice(node), label: `${node.node_name || node.node_id} · ${label('placementUnavailable')}`, disabled: true }] : []),
      ]}
      onChange={value => {
        const row = options.get(value);
        setNode(row);
        selectWorkbenchNode(row && { node_id: row.node_id, deployment_id: row.deployment_id });
      }} />
    {unavailable ? <small role="status">{label('workbenchUnavailable')}</small> : null}
    {actual ? <small role="status">{label('actualNode')} {actual}</small> : selected ? <small role="status">{label('workbenchQueued')} {selected}</small> : null}
  </HStack>;
}
